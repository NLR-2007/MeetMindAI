"""Tests for calendar scheduling and the Whisper fallback."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from app.config import get_settings
from app.models import Calendar
from app.services.calendar import CalendarError, build_authorization_url

BASE = get_settings().recall_api_base
GOOD_URL = "https://meet.google.com/abc-defg-hij"


# --- Google OAuth --------------------------------------------------------


def test_authorization_url_requests_offline_refresh_token() -> None:
    settings = get_settings()
    url = build_authorization_url(settings, "state123")
    params = parse_qs(urlparse(url).query)

    # Without access_type=offline AND prompt=consent Google withholds the
    # refresh token, which Recall requires.
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["state"] == ["state123"]
    # Full calendar scope: needed to create the dedicated MeetMind calendar.
    scope = params["scope"][0]
    assert "https://www.googleapis.com/auth/calendar" in scope
    assert "calendar.events.readonly" not in scope


def test_authorization_url_requires_credentials(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_secret", None)
    with pytest.raises(CalendarError, match="GOOGLE_CLIENT_SECRET"):
        build_authorization_url(settings, "s")


def test_oauth_callback_rejects_unknown_state(client) -> None:
    resp = client.get(
        "/calendar/oauth/callback?code=abc&state=never_issued",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "invalid_state" in resp.headers["location"]


def test_oauth_start_returns_consent_url(client) -> None:
    body = client.get("/calendar/oauth/start").json()
    assert body["authorization_url"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth?"
    )


# --- Calendar events -----------------------------------------------------


@respx.mock
def test_list_events_marks_scheduled_bots(client, db, user) -> None:
    calendar = Calendar(recall_calendar_id="cal_1", email="a@b.com", owner_id=user.id)
    db.add(calendar)
    db.commit()

    respx.get(f"{BASE}/api/v2/calendar-events/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "evt_1",
                        "start_time": "2026-10-01T10:00:00Z",
                        "end_time": "2026-10-01T11:00:00Z",
                        "meeting_url": GOOD_URL,
                        "meeting_platform": "google_meet",
                        "raw": {"summary": "Weekly sync"},
                        "bots": [{"bot_id": "bot_x"}],
                    },
                    {
                        "id": "evt_2",
                        "start_time": "2026-10-02T10:00:00Z",
                        "end_time": "2026-10-02T11:00:00Z",
                        "meeting_url": None,
                        "raw": {"summary": "Focus time"},
                        "bots": [],
                    },
                ]
            },
        )
    )

    events = client.get(f"/calendar/{calendar.id}/events").json()
    assert events[0]["title"] == "Weekly sync"
    assert events[0]["bot_scheduled"] is True
    assert events[1]["bot_scheduled"] is False


def test_list_events_unknown_calendar_is_404(client) -> None:
    assert client.get("/calendar/nope/events").status_code == 404


def test_schedule_requires_consent(client) -> None:
    resp = client.post("/calendar/events/evt_1/schedule")
    assert resp.status_code == 422
    assert "consent_acknowledged" in resp.json()["detail"]


@respx.mock
def test_schedule_sends_documented_payload(client) -> None:
    route = respx.post(f"{BASE}/api/v2/calendar-events/evt_1/bot/").mock(
        return_value=httpx.Response(200, json={"id": "evt_1", "bots": [{"bot_id": "b1"}]})
    )

    resp = client.post("/calendar/events/evt_1/schedule?consent_acknowledged=true")
    assert resp.status_code == 201

    payload = json.loads(route.calls.last.request.content)
    assert payload["deduplication_key"] == "meetmind-evt_1"
    assert payload["bot_config"]["bot_name"] == "MeetMind AI Notetaker"
    assert payload["bot_config"]["recording_config"]["transcript"]["provider"][
        "recallai_streaming"
    ] == {"mode": "prioritize_accuracy", "language_code": "en"}


# --- Whisper fallback ----------------------------------------------------


@respx.mock
def test_whisper_fallback_used_when_no_transcript(client) -> None:
    """No Recall transcript but audio present: Groq Whisper fills the gap."""
    respx.post(f"{BASE}/api/v1/bot/").mock(
        return_value=httpx.Response(201, json={"id": "bot_w", "status_changes": []})
    )
    meeting = client.post(
        "/meetings/join", json={"meeting_url": GOOD_URL, "consent_acknowledged": True}
    ).json()

    audio_url = "https://s3.example.com/audio.mp3?sig=x"
    respx.get(f"{BASE}/api/v1/bot/bot_w/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "bot_w",
                "status_changes": [{"code": "done"}],
                "recordings": [
                    {
                        "id": "rec_w",
                        "media_shortcuts": {
                            # transcript absent entirely
                            "audio_mixed": {"data": {"download_url": audio_url}}
                        },
                    }
                ],
            },
        )
    )
    respx.get(audio_url).mock(return_value=httpx.Response(200, content=b"fake-audio"))
    respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "We shipped the release."})
    )
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Release shipped.",
                                    "decisions": [],
                                    "action_items": [],
                                    "deadlines": [],
                                    "participants": [],
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 10},
            },
        )
    )

    result = client.post(f"/meetings/{meeting['id']}/process").json()
    assert result["transcript_saved"] is True
    assert result["used_whisper_fallback"] is True

    detail = client.get(f"/meetings/{meeting['id']}?include_transcript=true").json()
    assert detail["transcript_text"] == "We shipped the release."
    # Whisper gives no diarisation, so no participants are inferred.
    assert detail["participants"] == []


@respx.mock
def test_no_transcript_and_no_audio_is_graceful(client) -> None:
    respx.post(f"{BASE}/api/v1/bot/").mock(
        return_value=httpx.Response(201, json={"id": "bot_n", "status_changes": []})
    )
    meeting = client.post(
        "/meetings/join", json={"meeting_url": GOOD_URL, "consent_acknowledged": True}
    ).json()

    respx.get(f"{BASE}/api/v1/bot/bot_n/").mock(
        return_value=httpx.Response(
            200,
            json={"id": "bot_n", "status_changes": [], "recordings": [{"id": "r", "media_shortcuts": {}}]},
        )
    )

    result = client.post(f"/meetings/{meeting['id']}/process").json()
    assert result["transcript_saved"] is False
    assert "no audio to fall back on" in result["skipped_reason"]


@respx.mock
def test_reconnect_replaces_previous_calendar(client, db, user) -> None:
    """Reconnecting the same email must not stack duplicate calendars."""
    from app.routers.calendar import _new_state

    db.add(Calendar(recall_calendar_id="cal_old", email="a@b.com", owner_id=user.id))
    db.commit()

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "at", "refresh_token": "rt"}
        )
    )
    respx.get("https://www.googleapis.com/oauth2/v2/userinfo").mock(
        return_value=httpx.Response(200, json={"email": "a@b.com"})
    )
    respx.post(f"{BASE}/api/v2/calendars/").mock(
        return_value=httpx.Response(
            200, json={"id": "cal_new", "platform": "google_calendar", "status": "connecting"}
        )
    )
    deleted = respx.delete(f"{BASE}/api/v2/calendars/cal_old/").mock(
        return_value=httpx.Response(204)
    )
    # Listing refreshes any calendar still in a non-settled state.
    respx.get(f"{BASE}/api/v2/calendars/cal_new/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "cal_new",
                "status": "connected",
                "platform_email": "a@b.com",
            },
        )
    )

    resp = client.get(
        f"/calendar/oauth/callback?code=xyz&state={_new_state(user.id)}", follow_redirects=False
    )
    assert resp.status_code == 303
    assert "connected=1" in resp.headers["location"]
    assert deleted.called

    rows = client.get("/calendar").json()
    assert [r["recall_calendar_id"] for r in rows] == ["cal_new"]


# --- Deadline → Google Calendar -----------------------------------------


def _seed_deadline(db, *, due_at, when_text="28-9-2026", owner_id=None):
    from datetime import datetime, timezone

    from app.models import Deadline, Meeting

    meeting = Meeting(
        owner_id=owner_id,
        bot_id=f"bot_dl_{when_text}",
        meeting_url=GOOD_URL,
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        title="Planning",
        status="done",
    )
    db.add(meeting)
    db.flush()
    deadline = Deadline(
        meeting_id=meeting.id,
        what="Project completion",
        when_text=when_text,
        due_at=due_at,
    )
    db.add(deadline)
    db.commit()
    return deadline


def test_iso_date_parsing_rejects_guesses() -> None:
    from app.services.meeting_service import _parse_iso_date

    assert _parse_iso_date("2026-09-28").date().isoformat() == "2026-09-28"
    # Anything not ISO becomes "no date" rather than a wrong date.
    assert _parse_iso_date("28-9-2026") is None
    assert _parse_iso_date("next Friday") is None
    assert _parse_iso_date(None) is None


def test_push_without_date_is_refused(client, db, user) -> None:
    deadline = _seed_deadline(db, due_at=None, when_text="soon", owner_id=user.id)
    resp = client.post(f"/calendar/deadlines/{deadline.id}/push")
    assert resp.status_code == 422
    assert "no resolvable date" in resp.json()["detail"]


def test_push_without_connected_calendar_is_refused(client, db, user) -> None:
    from datetime import datetime, timezone

    deadline = _seed_deadline(
        db,
        due_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        when_text="dl1",
        owner_id=user.id,
    )
    resp = client.post(f"/calendar/deadlines/{deadline.id}/push")
    assert resp.status_code == 409
    assert "No calendar is connected" in resp.json()["detail"]


@respx.mock
def test_push_creates_all_day_event(client, db, user) -> None:
    from datetime import datetime, timezone

    db.add(Calendar(recall_calendar_id="cal_w", email="a@b.com", owner_id=user.id,
                    google_refresh_token="rt_123", status="connected"))
    deadline = _seed_deadline(
        db,
        due_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        when_text="dl2",
        owner_id=user.id,
    )

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "at_1"})
    )
    # No MeetMind calendar exists yet, so one is created on first push.
    respx.get("https://www.googleapis.com/calendar/v3/users/me/calendarList").mock(
        return_value=httpx.Response(200, json={"items": [{"id": "primary", "summary": "Bunny"}]})
    )
    made_calendar = respx.post("https://www.googleapis.com/calendar/v3/calendars").mock(
        return_value=httpx.Response(200, json={"id": "mm_cal_1", "summary": "MeetMind AI"})
    )
    route = respx.post(
        "https://www.googleapis.com/calendar/v3/calendars/mm_cal_1/events"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "gev_1", "htmlLink": "https://calendar.google.com/event?eid=1"}
        )
    )

    resp = client.post(f"/calendar/deadlines/{deadline.id}/push")
    assert resp.status_code == 201
    body = resp.json()
    assert body["google_event_id"] == "gev_1"
    assert body["date"] == "2026-09-28"

    sent = json.loads(route.calls.last.request.content)
    assert sent["summary"] == "Project completion"
    assert sent["start"]["date"] == "2026-09-28"
    # Google treats all-day end.date as exclusive.
    assert sent["end"]["date"] == "2026-09-29"

    # The event goes to a dedicated calendar, never the user's primary one.
    assert made_calendar.called
    assert json.loads(made_calendar.calls.last.request.content)["summary"] == "MeetMind AI"


@respx.mock
def test_push_is_idempotent(client, db, user) -> None:
    from datetime import datetime, timezone

    db.add(Calendar(recall_calendar_id="cal_i", email="a@b.com", owner_id=user.id,
                    google_refresh_token="rt", status="connected"))
    deadline = _seed_deadline(
        db,
        due_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        when_text="dl3",
        owner_id=user.id,
    )
    deadline.google_event_id = "already_there"
    db.commit()

    resp = client.post(f"/calendar/deadlines/{deadline.id}/push")
    assert resp.status_code == 201
    assert resp.json()["already_present"] is True


# --- Date resolution -----------------------------------------------------


def test_resolve_due_date_handles_real_phrasings() -> None:
    from datetime import datetime, timezone

    from app.services.meeting_service import resolve_due_date

    anchor = datetime(2026, 9, 27, tzinfo=timezone.utc)
    r = lambda iso, spoken: resolve_due_date(iso, spoken, anchor)  # noqa: E731

    # Spoken dates the model often refuses to normalise itself.
    assert r(None, "3rd of October").date().isoformat() == "2026-10-03"
    assert r(None, "1st of October").date().isoformat() == "2026-10-01"
    assert r(None, "2nd October").date().isoformat() == "2026-10-02"
    assert r(None, "30th of September").date().isoformat() == "2026-09-30"
    assert r(None, "28-9-2026").date().isoformat() == "2026-09-28"

    # A date already past rolls forward: a deadline is a future commitment.
    assert r(None, "13th of September").date().isoformat() == "2027-09-13"

    # Too vague to place on a calendar.
    assert r(None, "soon") is None
    assert r(None, "later this quarter") is None
    assert r(None, None) is None

    # An explicit ISO date from the model always wins.
    assert r("2026-10-05", "ignored").date().isoformat() == "2026-10-05"
