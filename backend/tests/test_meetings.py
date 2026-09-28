"""Meeting dispatch, validation, status and processing tests."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import get_settings
from app.schemas import detect_platform

BASE = get_settings().recall_api_base
GOOD_URL = "https://meet.google.com/abc-defg-hij"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://meet.google.com/abc-defg-hij", "google_meet"),
        ("https://zoom.us/j/1234567890", "zoom"),
        ("https://teams.microsoft.com/l/meetup-join/xyz", "teams"),
        ("https://example.com/not-a-meeting", None),
        ("https://meet.google.com/tooshort", None),
    ],
)
def test_detect_platform(url: str, expected: str | None) -> None:
    assert detect_platform(url) == expected


def test_health_reports_config(client) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["recall_region"] == "us-west-2"
    assert body["recall_api_key_present"] is True
    # Never claim Hindsight works until it does.
    assert body["hindsight_integrated"] is False


def test_join_rejects_unknown_url(client) -> None:
    resp = client.post(
        "/meetings/join",
        json={"meeting_url": "https://example.com/xyz", "consent_acknowledged": True},
    )
    assert resp.status_code == 422


def test_join_requires_consent(client) -> None:
    resp = client.post(
        "/meetings/join", json={"meeting_url": GOOD_URL, "consent_acknowledged": False}
    )
    assert resp.status_code == 422
    assert "consent_acknowledged" in resp.text


def test_status_unknown_meeting_is_404(client) -> None:
    assert client.get("/meetings/nope/status").status_code == 404


@respx.mock
def test_join_sends_documented_payload(client) -> None:
    route = respx.post(f"{BASE}/api/v1/bot/").mock(
        return_value=httpx.Response(
            201, json={"id": "bot_test_123", "status_changes": [{"code": "joining_call"}]}
        )
    )

    resp = client.post(
        "/meetings/join",
        json={"meeting_url": GOOD_URL, "consent_acknowledged": True, "title": "Standup"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["bot_id"] == "bot_test_123"
    assert body["platform"] == "google_meet"
    assert body["status"] == "joining_call"
    assert body["title"] == "Standup"

    sent = route.calls.last.request
    assert sent.headers["authorization"].startswith("Token ")
    payload = json.loads(sent.content)
    assert payload["meeting_url"] == GOOD_URL
    assert payload["bot_name"] == "MeetMind AI Notetaker"
    # Exact field path from the Recall transcription docs.
    assert payload["recording_config"]["transcript"]["provider"]["recallai_streaming"] == {
        # Live joins stream transcript in real time, so latency wins here.
        "mode": "prioritize_low_latency",
        "language_code": "en",
    }


@respx.mock
def test_join_surfaces_recall_error(client) -> None:
    respx.post(f"{BASE}/api/v1/bot/").mock(
        return_value=httpx.Response(400, json={"meeting_url": ["Invalid meeting URL."]})
    )
    resp = client.post(
        "/meetings/join", json={"meeting_url": GOOD_URL, "consent_acknowledged": True}
    )
    assert resp.status_code == 502
    assert "Invalid meeting URL" in resp.text


@respx.mock
def test_join_then_history_and_detail(client) -> None:
    respx.post(f"{BASE}/api/v1/bot/").mock(
        return_value=httpx.Response(201, json={"id": "bot_hist", "status_changes": []})
    )
    created = client.post(
        "/meetings/join", json={"meeting_url": GOOD_URL, "consent_acknowledged": True}
    ).json()

    history = client.get("/meetings").json()
    assert [m["id"] for m in history] == [created["id"]]

    detail = client.get(f"/meetings/{created['id']}").json()
    assert detail["has_transcript"] is False
    assert detail["summary"] is None


@respx.mock
def test_process_persists_transcript_and_analysis(client) -> None:
    """Full pipeline against the real Recall/Groq response shapes."""
    respx.post(f"{BASE}/api/v1/bot/").mock(
        return_value=httpx.Response(201, json={"id": "bot_proc", "status_changes": []})
    )
    meeting = client.post(
        "/meetings/join", json={"meeting_url": GOOD_URL, "consent_acknowledged": True}
    ).json()

    transcript_url = "https://s3.example.com/transcript.json?sig=abc"
    respx.get(f"{BASE}/api/v1/bot/bot_proc/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "bot_proc",
                "status_changes": [{"code": "done"}],
                "recordings": [
                    {
                        "id": "rec_1",
                        "media_shortcuts": {
                            "transcript": {
                                "status": {"code": "done"},
                                "data": {"download_url": transcript_url},
                            }
                        },
                    }
                ],
            },
        )
    )
    # Shape verified against a real Recall transcript download.
    respx.get(transcript_url).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "participant": {
                        "id": 100,
                        "name": "Bunny Reddy",
                        "is_host": True,
                        "email": None,
                        "platform": "desktop",
                    },
                    "words": [
                        {"text": "Ship"},
                        {"text": "the"},
                        {"text": "API"},
                        {"text": "by"},
                        {"text": "Friday."},
                    ],
                }
            ],
        )
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
                                    "summary": "Team agreed to ship the API.",
                                    "decisions": ["Ship the API"],
                                    "action_items": [
                                        {
                                            "task": "Ship the API",
                                            "owner": "Bunny Reddy",
                                            "due": "Friday",
                                        }
                                    ],
                                    "deadlines": [
                                        {"what": "API release", "when": "Friday"}
                                    ],
                                    "participants": ["Bunny Reddy"],
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 321},
            },
        )
    )

    result = client.post(f"/meetings/{meeting['id']}/process").json()
    assert result["transcript_saved"] is True
    assert result["analysis_saved"] is True
    assert result["participants"] == 1
    assert result["action_items"] == 1

    detail = client.get(f"/meetings/{meeting['id']}?include_transcript=true").json()
    assert detail["summary"]["summary_text"] == "Team agreed to ship the API."
    assert detail["summary"]["decisions"] == ["Ship the API"]
    assert detail["action_items"][0]["owner_name"] == "Bunny Reddy"
    assert detail["deadlines"][0]["when_text"] == "Friday"
    assert detail["participants"][0]["name"] == "Bunny Reddy"
    assert "Bunny Reddy: Ship the API by Friday." in detail["transcript_text"]


@respx.mock
def test_process_without_transcript_is_graceful(client) -> None:
    respx.post(f"{BASE}/api/v1/bot/").mock(
        return_value=httpx.Response(201, json={"id": "bot_none", "status_changes": []})
    )
    meeting = client.post(
        "/meetings/join", json={"meeting_url": GOOD_URL, "consent_acknowledged": True}
    ).json()

    respx.get(f"{BASE}/api/v1/bot/bot_none/").mock(
        return_value=httpx.Response(
            200, json={"id": "bot_none", "status_changes": [], "recordings": []}
        )
    )

    result = client.post(f"/meetings/{meeting['id']}/process").json()
    assert result["transcript_saved"] is False
    assert "no transcript available" in result["skipped_reason"]
