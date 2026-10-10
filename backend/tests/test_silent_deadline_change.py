"""A deadline that moves without anyone saying so must not pass quietly.

The dangerous case is not an argument about a date. It is the meeting where a
date is restated differently and nobody notices, so two people leave believing
two different things. These tests pin the distinction between a change that was
announced and one that was not.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.models import Commitment, Deadline, Meeting, Project, Transcript
from app.services import promisemirror

WHAT = "Submit the compliance report"


def _project(db, user_id: str) -> Project:
    project = Project(owner_id=user_id, name="Compliance rollout")
    db.add(project)
    db.flush()
    return project


def _meeting_with_deadline(
    db, user_id: str, project_id: str, *, title: str, day: int, transcript: str
) -> Meeting:
    meeting = Meeting(
        owner_id=user_id,
        project_id=project_id,
        bot_id=f"bot_{title.replace(' ', '_')}",
        meeting_url="https://meet.google.com/abc-defg-hij",
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        title=title,
        status="done",
    )
    db.add(meeting)
    db.flush()
    db.add(
        Transcript(
            meeting_id=meeting.id,
            plain_text=transcript,
            word_count=len(transcript.split()),
        )
    )
    db.add(
        Deadline(
            meeting_id=meeting.id,
            what=WHAT,
            due_at=datetime(2026, 9, day, tzinfo=UTC),
            when_text=f"{day} September",
        )
    )
    db.flush()
    db.refresh(meeting)
    return meeting


def test_unannounced_date_shift_is_flagged_and_original_quoted(db, user) -> None:
    project = _project(db, user.id)
    first = _meeting_with_deadline(
        db,
        user.id,
        project.id,
        title="Kickoff",
        day=20,
        transcript="Nimma: We will submit the compliance report on the twentieth of September.",
    )
    assert promisemirror.sync_meeting_commitments(db, first)["created"] == 1

    second = _meeting_with_deadline(
        db,
        user.id,
        project.id,
        title="Weekly check-in",
        day=19,
        transcript="Nimma: Right, so submit the compliance report on the nineteenth of September.",
    )
    result = promisemirror.sync_meeting_commitments(db, second)
    assert result["superseded"] == 1
    assert result["silent_changes"] == 1

    replacement = db.scalars(
        Commitment.__table__.select().where(
            Commitment.__table__.c.source_meeting_id == second.id
        )
    ).first()
    assert replacement is not None

    findings = promisemirror.analyse(db, owner_user_id=user.id, project_id=project.id)
    silent = [f for f in findings if f.kind == "silent_change"]
    assert len(silent) == 1
    assert silent[0].severity == "high"
    # The whole point: it names the date that was actually agreed.
    assert "2026-09-20" in silent[0].detail
    assert "Kickoff" in silent[0].detail
    assert "Weekly check-in" in silent[0].detail


def test_announced_change_is_an_ordinary_revision(db, user) -> None:
    project = _project(db, user.id)
    first = _meeting_with_deadline(
        db,
        user.id,
        project.id,
        title="Kickoff",
        day=20,
        transcript="Nimma: We will submit the compliance report on the twentieth.",
    )
    promisemirror.sync_meeting_commitments(db, first)

    second = _meeting_with_deadline(
        db,
        user.id,
        project.id,
        title="Weekly check-in",
        day=19,
        transcript=(
            "Nimma: We moved the compliance report submission to the nineteenth "
            "instead of the twentieth, because audit needs it a day early."
        ),
    )
    result = promisemirror.sync_meeting_commitments(db, second)
    assert result["superseded"] == 1
    assert result["silent_changes"] == 0

    findings = promisemirror.analyse(db, owner_user_id=user.id, project_id=project.id)
    assert [f.kind for f in findings if f.kind == "silent_change"] == []
    changed = [f for f in findings if f.kind == "changed"]
    assert len(changed) == 1
    assert changed[0].severity == "medium"


def test_change_language_about_something_else_does_not_excuse_the_shift(db, user) -> None:
    project = _project(db, user.id)
    first = _meeting_with_deadline(
        db, user.id, project.id, title="Kickoff", day=20,
        transcript="Nimma: Compliance report on the twentieth.",
    )
    promisemirror.sync_meeting_commitments(db, first)

    second = _meeting_with_deadline(
        db, user.id, project.id, title="Weekly check-in", day=19,
        transcript=(
            "Nimma: We moved the all-hands to Thursday and the venue changed to the annexe. "
            "Separately, compliance report on the nineteenth."
        ),
    )
    assert promisemirror.sync_meeting_commitments(db, second)["silent_changes"] == 1


def test_owner_can_reinstate_the_agreed_date(client, db, user) -> None:
    project = _project(db, user.id)
    first = _meeting_with_deadline(
        db, user.id, project.id, title="Kickoff", day=20,
        transcript="Nimma: Compliance report on the twentieth.",
    )
    promisemirror.sync_meeting_commitments(db, first)
    second = _meeting_with_deadline(
        db, user.id, project.id, title="Weekly check-in", day=19,
        transcript="Nimma: Compliance report on the nineteenth.",
    )
    promisemirror.sync_meeting_commitments(db, second)
    db.commit()

    replacement = next(
        c for c in db.query(Commitment).all() if c.source_meeting_id == second.id
    )
    original_id = replacement.supersedes_id

    resp = client.post(
        f"/promisemirror/commitments/{replacement.id}/resolve-change",
        json={"keep": "original"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == original_id
    assert resp.json()["due_at"].startswith("2026-09-20")

    db.expire_all()
    assert db.get(Commitment, original_id).status == "pending"
    assert db.get(Commitment, replacement.id).status == "cancelled"
    # Resolved, so the alert stops.
    findings = promisemirror.analyse(db, owner_user_id=user.id, project_id=project.id)
    assert [f.kind for f in findings if f.kind == "silent_change"] == []


def test_owner_can_accept_the_new_date(client, db, user) -> None:
    project = _project(db, user.id)
    first = _meeting_with_deadline(
        db, user.id, project.id, title="Kickoff", day=20,
        transcript="Nimma: Compliance report on the twentieth.",
    )
    promisemirror.sync_meeting_commitments(db, first)
    second = _meeting_with_deadline(
        db, user.id, project.id, title="Weekly check-in", day=19,
        transcript="Nimma: Compliance report on the nineteenth.",
    )
    promisemirror.sync_meeting_commitments(db, second)
    db.commit()

    replacement = next(
        c for c in db.query(Commitment).all() if c.source_meeting_id == second.id
    )
    resp = client.post(
        f"/promisemirror/commitments/{replacement.id}/resolve-change",
        json={"keep": "new"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["confirmed"] is True

    db.expire_all()
    findings = promisemirror.analyse(db, owner_user_id=user.id, project_id=project.id)
    assert [f.kind for f in findings if f.kind == "silent_change"] == []
    # Still recorded as a change, just an accepted one.
    assert any(f.kind == "changed" for f in findings)


def test_filtering_by_meeting_keeps_the_change_visible(db, user) -> None:
    """A per-meeting view must not hide a silent change.

    A change is a pair — the original from one meeting, the replacement from
    another. Scoping on source_meeting_id alone dropped the original, so the
    pair was never whole and the alert disappeared from the meeting filter on
    My Promises and from a Co-Work board.
    """
    project = _project(db, user.id)
    first = _meeting_with_deadline(
        db, user.id, project.id, title="Kickoff", day=20,
        transcript="Nimma: Compliance report on the twentieth.",
    )
    promisemirror.sync_meeting_commitments(db, first)
    second = _meeting_with_deadline(
        db, user.id, project.id, title="Weekly check-in", day=19,
        transcript="Nimma: Compliance report on the nineteenth.",
    )
    promisemirror.sync_meeting_commitments(db, second)

    scoped = promisemirror.analyse(
        db, owner_user_id=user.id, meeting_id=second.id
    )
    assert [f.kind for f in scoped if f.kind == "silent_change"] == ["silent_change"]

    # It shows against the earlier meeting too, and should: from the meeting
    # where the date was agreed, "what we settled here has since moved" is
    # exactly the thing worth knowing.
    earlier = promisemirror.analyse(db, owner_user_id=user.id, meeting_id=first.id)
    assert [f.kind for f in earlier if f.kind == "silent_change"] == ["silent_change"]
