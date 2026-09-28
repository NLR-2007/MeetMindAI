"""Coaching must review only the requesting user's own words."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.models import Meeting, Transcript, User
from app.services.markup import split_transcript_by_speaker
from app.services.security import hash_password

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TRANSCRIPT = "\n".join(
    [
        "Bunny Reddy: I will finish the demo video by Friday.",
        "Akhil: I have not started the authentication tests yet.",
        "Priya: What about the budget? Nobody answered that.",
        "Bunny Reddy: We should use the thing for the stuff.",
    ]
)


def _meeting(db, owner: User) -> Meeting:
    m = Meeting(
        owner_id=owner.id,
        bot_id=f"bot_coach_{owner.id[:6]}",
        meeting_url="https://meet.google.com/abc-defg-hij",
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        title="Team sync",
        status="done",
    )
    db.add(m)
    db.flush()
    db.add(Transcript(meeting_id=m.id, plain_text=TRANSCRIPT, word_count=30))
    db.commit()
    return m


# --- the split itself ------------------------------------------------------


def test_split_matches_on_the_speaker_prefix_only() -> None:
    mine, others = split_transcript_by_speaker(TRANSCRIPT, ["Bunny Reddy", "Bunny"])
    assert len(mine) == 2
    assert all(line.startswith("Bunny Reddy:") for line in mine)
    # Akhil's and Priya's lines are context, never mine.
    assert len(others) == 2


def test_being_mentioned_does_not_claim_someone_elses_line() -> None:
    text = "Akhil: Bunny will finish the demo video."
    mine, others = split_transcript_by_speaker(text, ["Bunny"])
    # "Bunny" appears in the sentence but Akhil is the speaker.
    assert mine == []
    assert len(others) == 1


def test_unknown_speaker_gets_nothing() -> None:
    mine, _ = split_transcript_by_speaker(TRANSCRIPT, ["Somebody Else"])
    assert mine == []


# --- end to end through the API -------------------------------------------


@respx.mock
def test_review_only_sends_and_keeps_the_users_own_lines(client, db, user) -> None:
    user.name = "Bunny Reddy"
    user.display_names = ["Bunny Reddy", "Bunny"]
    db.commit()
    meeting = _meeting(db, user)

    route = respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "suggestions": [
                                        {
                                            "category": "clarity",
                                            "said": "We should use the thing for the stuff.",
                                            "issue": "Vague — 'the thing' and 'the stuff' name nothing.",
                                            "better": "We should use Hindsight for meeting memory.",
                                            "evidence": "We should use the thing for the stuff.",
                                        },
                                        {
                                            # Quotes Akhil, not this user: must be dropped.
                                            "category": "missed_point",
                                            "said": "Nothing",
                                            "issue": "Did not start the authentication tests.",
                                            "better": "I will start the auth tests tomorrow.",
                                            "evidence": "I have not started the authentication tests yet.",
                                        },
                                    ]
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 100},
            },
        )
    )

    resp = client.post(f"/coach/{meeting.id}/review", json={})
    assert resp.status_code == 201
    body = resp.json()

    # The suggestion quoting Akhil was discarded.
    assert body["count"] == 1
    note = body["notes"][0]
    assert note["said"] == "We should use the thing for the stuff."
    assert note["better"] == "We should use Hindsight for meeting memory."

    # The prompt marked this user's lines and never presented others as theirs.
    sent = json.loads(route.calls.last.request.content)
    prompt = " ".join(m["content"] for m in sent["messages"])
    assert "THIS PERSON'S LINES (Bunny Reddy)" in prompt
    assert "OTHER SPEAKERS" in prompt


@respx.mock
def test_review_refuses_when_the_user_never_spoke(client, db, user) -> None:
    """Better to refuse than to review someone else's words as yours."""
    user.name = "Ghost"
    user.display_names = ["Ghost"]
    db.commit()
    meeting = _meeting(db, user)

    resp = client.post(f"/coach/{meeting.id}/review", json={})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "Could not find you in this transcript" in detail
    # It tells them who it did hear, so they can fix their aliases.
    assert "Bunny Reddy" in detail


def test_one_users_notes_are_invisible_to_another(client, other_client, db, user) -> None:
    from app.models import CoachingNote

    meeting = _meeting(db, user)
    db.add(
        CoachingNote(
            owner_user_id=user.id,
            meeting_id=meeting.id,
            category="clarity",
            suggestion="Be specific",
            said="the thing",
            better="Hindsight",
        )
    )
    db.commit()

    assert len(client.get("/coach/notes").json()["notes"]) == 1
    # A different person must not see it, even for the same meeting.
    assert other_client.get("/coach/notes").json()["notes"] == []
