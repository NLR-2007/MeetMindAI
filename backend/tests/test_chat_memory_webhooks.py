"""Tests for meeting-scoped chat, MemoryService, and webhook verification."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import respx

from app.models import Meeting, Summary, Transcript
from app.services.memory import MySQLMemoryService, get_memory_service

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _seed_meeting(db, *, bot_id="bot_chat", title="Alpha planning", owner_id=None) -> Meeting:
    meeting = Meeting(
        owner_id=owner_id,
        bot_id=bot_id,
        meeting_url="https://meet.google.com/abc-defg-hij",
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        title=title,
        status="done",
        consent_acknowledged=True,
    )
    db.add(meeting)
    db.flush()
    db.add(
        Transcript(
            meeting_id=meeting.id,
            plain_text="Bunny Reddy: We will ship the API on Friday.",
            word_count=8,
        )
    )
    db.add(
        Summary(
            meeting_id=meeting.id,
            summary_text="Team agreed to ship the API on Friday.",
            decisions=["Ship the API on Friday"],
        )
    )
    db.commit()
    return meeting


# --- MemoryService -------------------------------------------------------


def test_memory_save_and_recall(db) -> None:
    service = MySQLMemoryService(db)
    service.save_memory("Ship the API on Friday", scope="meeting", scope_id="m1")
    service.save_memory("Hire a designer", scope="meeting", scope_id="m1")
    service.save_memory("Unrelated other meeting", scope="meeting", scope_id="m2")
    db.commit()

    results = service.recall_memory("when do we ship the API", scope_id="m1")
    assert len(results) == 2
    # Lexical ranking should surface the API memory first.
    assert "API" in results[0]["content"]

    other = service.recall_memory("anything", scope_id="m2")
    assert len(other) == 1


def test_memory_scope_isolation(db) -> None:
    service = get_memory_service(db)
    service.save_memory("secret from meeting A", scope="meeting", scope_id="A")
    db.commit()
    assert service.recall_memory("secret", scope_id="B") == []


def test_hindsight_is_not_claimed_as_integrated(db) -> None:
    service = get_memory_service(db)
    assert isinstance(service, MySQLMemoryService)
    assert service.is_persistent_memory_backend is False
    assert service.backend_name == "mysql"


# --- Chat ----------------------------------------------------------------


def test_chat_unknown_meeting_is_404(client) -> None:
    resp = client.post("/meetings/missing/chat", json={"message": "hello"})
    assert resp.status_code == 404


def test_chat_requires_transcript(client, db, user) -> None:
    meeting = Meeting(
        owner_id=user.id,
        bot_id="bot_empty",
        meeting_url="https://meet.google.com/abc-defg-hij",
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        status="done",
    )
    db.add(meeting)
    db.commit()

    resp = client.post(f"/meetings/{meeting.id}/chat", json={"message": "what happened?"})
    assert resp.status_code == 409
    assert "process" in resp.json()["detail"]


@respx.mock
def test_chat_answers_from_meeting_context(client, db, user) -> None:
    meeting = _seed_meeting(db, owner_id=user.id)
    route = respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "On Friday."}}
                ],
                "usage": {"total_tokens": 42},
            },
        )
    )

    resp = client.post(f"/meetings/{meeting.id}/chat", json={"message": "When do we ship?"})
    assert resp.status_code == 200
    assert resp.json()["answer"] == "On Friday."

    sent = json.loads(route.calls.last.request.content)
    context = " ".join(m["content"] for m in sent["messages"])
    # The prompt must carry this meeting's records and nothing else.
    assert "ship the API on Friday" in context
    assert "ONE specific meeting" in context

    history = client.get(f"/meetings/{meeting.id}/chat").json()
    assert [m["role"] for m in history] == ["user", "assistant"]


@respx.mock
def test_chat_asks_before_switching_meetings(client, db, user) -> None:
    current = _seed_meeting(db, bot_id="bot_a", title="Alpha planning", owner_id=user.id)
    other = _seed_meeting(db, bot_id="bot_b", title="Budget review", owner_id=user.id)
    respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "hi"}}],
                "usage": {"total_tokens": 1},
            },
        )
    )

    resp = client.post(
        f"/meetings/{current.id}/chat",
        json={"message": "What did we say in Budget review?"},
    )
    body = resp.json()
    assert body["context_switch_required"] is True
    assert body["pending_meeting_id"] == other.id
    # No answer should be produced until the switch is confirmed.
    assert "Confirm the switch" in body["answer"]


# --- Webhooks ------------------------------------------------------------


def test_webhook_rejected_without_secret(client, monkeypatch) -> None:
    """Unverified webhooks must not be accepted by default."""
    from app.config import get_settings

    # Explicit, so the result does not depend on what .env happens to hold.
    monkeypatch.setattr(get_settings(), "recall_webhook_secret", None)

    resp = client.post("/webhooks/recall", json={"event": "bot.done"})
    assert resp.status_code == 401
    assert "RECALL_WEBHOOK_SECRET" in resp.json()["detail"]


def test_webhook_rejects_bad_signature(client, monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "recall_webhook_secret", "whsec_" + "A" * 32)

    resp = client.post(
        "/webhooks/recall",
        json={"event": "bot.done"},
        headers={
            "webhook-id": "msg_1",
            "webhook-timestamp": "1700000000",
            "webhook-signature": "v1,bogus",
        },
    )
    assert resp.status_code == 401
    assert "signature" in resp.json()["detail"].lower()


def test_webhook_accepts_valid_signature(client, db, user, monkeypatch) -> None:
    from svix.webhooks import Webhook

    from app.config import get_settings

    secret = "whsec_" + "A" * 32
    settings = get_settings()
    monkeypatch.setattr(settings, "recall_webhook_secret", secret)

    _seed_meeting(db, bot_id="bot_hook", owner_id=user.id)
    payload = json.dumps(
        {"event": "bot.status_change", "data": {"bot_id": "bot_hook",
                                                "status": {"code": "in_call_recording"}}}
    )
    # Svix enforces replay protection, so the timestamp must be recent.
    now = datetime.now(timezone.utc)
    msg_id, timestamp = "msg_2", int(now.timestamp())
    signature = Webhook(secret).sign(msg_id, now, payload)

    resp = client.post(
        "/webhooks/recall",
        content=payload,
        headers={
            "content-type": "application/json",
            "webhook-id": msg_id,
            "webhook-timestamp": str(timestamp),
            "webhook-signature": signature,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_realtime_webhook_saves_live_utterance(client, db, user, monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "recall_webhook_secret", None)
    monkeypatch.setattr(settings, "allow_unverified_webhooks", True)
    meeting = _seed_meeting(db, bot_id="bot_realtime", owner_id=user.id)

    response = client.post(
        "/webhooks/recall/realtime",
        json={
            "event": "transcript.data",
            "data": {
                "data": {
                    "words": [
                        {"text": "What", "start_timestamp": {"relative": 10.0}, "end_timestamp": {"relative": 10.2}},
                        {"text": "changed?", "start_timestamp": {"relative": 10.2}, "end_timestamp": {"relative": 10.7}},
                    ],
                    "participant": {"id": 9, "name": "Client", "email": "client@example.com"},
                },
                "bot": {"id": "bot_realtime", "metadata": {}},
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True
    db.expire_all()
    refreshed = db.get(Meeting, meeting.id)
    assert refreshed is not None and refreshed.transcript is not None
    assert refreshed.transcript.utterances[-1]["text"] == "What changed?"
