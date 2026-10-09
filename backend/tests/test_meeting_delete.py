"""Deleting a meeting removes everything derived from it, and nothing else."""
from __future__ import annotations

from app.models import (
    ActionItem,
    ChatMessage,
    CoachingNote,
    Commitment,
    Deadline,
    Meeting,
    Summary,
    Transcript,
)

GOOD_URL = "https://meet.google.com/abc-defg-hij"


def _full_meeting(db, owner_id: str, bot_id: str) -> Meeting:
    m = Meeting(
        owner_id=owner_id,
        bot_id=bot_id,
        meeting_url=GOOD_URL,
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        title="Disposable",
        status="done",
    )
    db.add(m)
    db.flush()
    db.add(Transcript(meeting_id=m.id, plain_text="Someone: hello", word_count=2))
    db.add(Summary(meeting_id=m.id, summary_text="A meeting", decisions=["Ship it"]))
    db.add(ActionItem(meeting_id=m.id, task="Do the thing"))
    db.add(Deadline(meeting_id=m.id, what="Ship", when_text="Friday"))
    db.add(ChatMessage(meeting_id=m.id, role="user", content="what happened?"))
    db.add(
        CoachingNote(
            owner_user_id=owner_id, meeting_id=m.id, category="clarity",
            suggestion="Be specific",
        )
    )
    db.add(
        Commitment(
            owner_user_id=owner_id, source_meeting_id=m.id,
            kind="promise", text="Ship the thing",
        )
    )
    db.commit()
    return m


def test_delete_removes_everything_derived(client, db, user) -> None:
    meeting = _full_meeting(db, user.id, "bot_delete_me")
    meeting_id = meeting.id

    resp = client.delete(f"/meetings/{meeting_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True
    assert body["commitments_removed"] == 1

    # The request used its own session; drop this one's cached copies.
    db.expire_all()
    assert db.get(Meeting, meeting_id) is None
    for model in (Transcript, Summary, ActionItem, Deadline, ChatMessage, CoachingNote):
        remaining = db.query(model).filter_by(meeting_id=meeting_id).all()
        assert remaining == [], f"{model.__name__} survived the delete"
    assert db.query(Commitment).filter_by(source_meeting_id=meeting_id).all() == []


def test_delete_leaves_other_meetings_alone(client, db, user) -> None:
    keep = _full_meeting(db, user.id, "bot_keep")
    drop = _full_meeting(db, user.id, "bot_drop")

    assert client.delete(f"/meetings/{drop.id}").status_code == 200

    db.expire_all()
    assert db.get(Meeting, keep.id) is not None
    assert db.query(Transcript).filter_by(meeting_id=keep.id).count() == 1
    assert db.query(Commitment).filter_by(source_meeting_id=keep.id).count() == 1


def test_cannot_delete_another_users_meeting(client, other_client, db, user) -> None:
    mine = _full_meeting(db, user.id, "bot_private")

    # 404, not 403: confirming it exists would itself be a disclosure.
    assert other_client.delete(f"/meetings/{mine.id}").status_code == 404
    db.expire_all()
    assert db.get(Meeting, mine.id) is not None


def test_delete_requires_authentication(anon_client, db, user) -> None:
    mine = _full_meeting(db, user.id, "bot_anon")
    assert anon_client.delete(f"/meetings/{mine.id}").status_code == 401
    db.expire_all()
    assert db.get(Meeting, mine.id) is not None


def test_supersession_chain_is_unlinked(client, db, user) -> None:
    """A surviving commitment must not point at a deleted one."""
    old_meeting = _full_meeting(db, user.id, "bot_old")
    new_meeting = _full_meeting(db, user.id, "bot_new")

    original = db.query(Commitment).filter_by(source_meeting_id=old_meeting.id).one()
    replacement = db.query(Commitment).filter_by(source_meeting_id=new_meeting.id).one()
    original.superseded_by_id = replacement.id
    replacement.supersedes_id = original.id
    db.commit()

    assert client.delete(f"/meetings/{old_meeting.id}").status_code == 200

    db.refresh(replacement)
    assert replacement.supersedes_id is None
