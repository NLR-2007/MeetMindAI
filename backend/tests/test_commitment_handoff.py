"""A promise can change hands, and the record has to follow it.

The scenario these pin down: someone takes a task, then says they cannot do
it after all. Either a colleague picks it up, or nobody does. Both must stop
the original owner from still carrying it, and the second must be loud about
the fact that it is now nobody's.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.models import ActionItem, Commitment, Meeting, Project, Transcript
from app.services import promisemirror
from app.services.promisemirror import _owner_changed

TASK = "Build the demo video and share it"


def _project(db, user_id: str) -> Project:
    project = Project(owner_id=user_id, name="Launch")
    db.add(project)
    db.flush()
    return project


def _meeting(
    db,
    user_id: str,
    project_id: str,
    *,
    title: str,
    owner: str | None,
    reassigned_from: str | None = None,
    transcript: str = "",
    due_text: str | None = "tomorrow",
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
        ActionItem(
            meeting_id=meeting.id,
            task=TASK,
            owner_name=owner,
            due_text=due_text,
            reassigned_from=reassigned_from,
        )
    )
    db.flush()
    db.refresh(meeting)
    return meeting


def _commitments(db) -> list[Commitment]:
    return list(db.query(Commitment).all())


# --- the owner comparison --------------------------------------------------


def test_owner_comparison_ignores_name_shortenings() -> None:
    """"Bunny" and "Bunny Reddy" are one person, not a handoff."""
    assert _owner_changed("Bunny Reddy", "Bunny") is False
    assert _owner_changed("bunny", "Bunny Reddy") is False
    assert _owner_changed("Bunny Reddy", "Akhil") is True


def test_a_missing_owner_alone_is_not_a_handoff() -> None:
    """A meeting that simply did not restate the owner must not orphan it."""
    assert _owner_changed("Bunny Reddy", None) is False
    assert _owner_changed("Bunny Reddy", "") is False


def test_first_owner_is_not_a_handoff() -> None:
    assert _owner_changed(None, "Bunny Reddy") is True


# --- handing over to a named person ---------------------------------------


def test_promise_handed_to_someone_else_leaves_the_original_owner(db, user) -> None:
    project = _project(db, user.id)
    first = _meeting(
        db, user.id, project.id, title="Kickoff", owner="Lokesh",
        transcript="Lokesh: Tomorrow I will build the demo video and share it.",
    )
    assert promisemirror.sync_meeting_commitments(db, first)["created"] == 1

    second = _meeting(
        db, user.id, project.id, title="Standup", owner="Akhil",
        reassigned_from="Lokesh",
        transcript=(
            "Lokesh: I am busy tomorrow, can someone handle the demo video?\n"
            "Akhil: I will build the demo video and share it."
        ),
    )
    result = promisemirror.sync_meeting_commitments(db, second)
    assert result["superseded"] == 1
    assert result["handoffs"] == 1
    # A handoff is an announced change, never a silent deadline move.
    assert result["silent_changes"] == 0

    rows = _commitments(db)
    original = next(c for c in rows if c.source_meeting_id == first.id)
    replacement = next(c for c in rows if c.source_meeting_id == second.id)

    assert original.status == "superseded"
    assert original.superseded_by_id == replacement.id
    assert replacement.owner_name == "Akhil"
    assert replacement.reassigned_from == "Lokesh"
    assert replacement.status == "pending"

    findings = promisemirror.analyse(db, owner_user_id=user.id, project_id=project.id)
    handed = [f for f in findings if f.kind == "handed_over"]
    assert len(handed) == 1
    assert "Lokesh" in handed[0].detail and "Akhil" in handed[0].detail
    # It is no longer reported as an ownerless promise.
    assert [f for f in findings if f.kind == "released"] == []


# --- giving it up with nobody taking it -----------------------------------


def test_promise_given_up_with_no_taker_is_flagged_loudly(db, user) -> None:
    project = _project(db, user.id)
    first = _meeting(
        db, user.id, project.id, title="Kickoff", owner="Lokesh",
        transcript="Lokesh: Tomorrow I will build the demo video and share it.",
    )
    promisemirror.sync_meeting_commitments(db, first)

    second = _meeting(
        db, user.id, project.id, title="Standup", owner=None,
        reassigned_from="Lokesh",
        transcript="Lokesh: I am busy tomorrow, can someone handle this?",
    )
    result = promisemirror.sync_meeting_commitments(db, second)
    assert result["superseded"] == 1
    assert result["handoffs"] == 1

    replacement = next(c for c in _commitments(db) if c.source_meeting_id == second.id)
    assert replacement.owner_name is None
    assert replacement.reassigned_from == "Lokesh"

    findings = promisemirror.analyse(db, owner_user_id=user.id, project_id=project.id)
    released = [f for f in findings if f.kind == "released"]
    assert len(released) == 1
    assert released[0].severity == "high"
    assert "Lokesh" in released[0].title
    # It must not ALSO appear as a generic ownerless task; one voice, not two.
    assert [f for f in findings if f.kind == "unowned"] == []


def test_a_plain_unowned_task_is_still_reported_as_unowned(db, user) -> None:
    """The release finding must not swallow ordinary ownerless work."""
    project = _project(db, user.id)
    meeting = _meeting(
        db, user.id, project.id, title="Kickoff", owner=None,
        transcript="Someone should build the demo video.",
    )
    promisemirror.sync_meeting_commitments(db, meeting)

    findings = promisemirror.analyse(db, owner_user_id=user.id, project_id=project.id)
    assert [f.kind for f in findings if f.kind == "unowned"] == ["unowned"]
    assert [f for f in findings if f.kind == "released"] == []


# --- the thing that must not regress --------------------------------------


def test_a_later_meeting_that_omits_the_owner_does_not_steal_the_promise(db, user) -> None:
    """Silence about ownership is not a handoff.

    Extraction routinely returns owner=null when a meeting mentions a task in
    passing. Treating that as a release would wipe the real owner.
    """
    project = _project(db, user.id)
    first = _meeting(
        db, user.id, project.id, title="Kickoff", owner="Lokesh",
        transcript="Lokesh: Tomorrow I will build the demo video and share it.",
    )
    promisemirror.sync_meeting_commitments(db, first)

    second = _meeting(
        db, user.id, project.id, title="Passing mention", owner=None,
        reassigned_from=None,
        transcript="Akhil: How is the demo video going?",
    )
    result = promisemirror.sync_meeting_commitments(db, second)
    assert result["handoffs"] == 0
    assert result["superseded"] == 0

    still = next(c for c in _commitments(db) if c.source_meeting_id == first.id)
    assert still.owner_name == "Lokesh"
    assert still.status == "pending"


def test_handoff_and_date_move_together_report_the_handoff(db, user) -> None:
    """When both change at once, who owns it is the more useful headline."""
    project = _project(db, user.id)
    first = _meeting(
        db, user.id, project.id, title="Kickoff", owner="Lokesh",
        transcript="Lokesh: I will build the demo video by Friday.",
    )
    promisemirror.sync_meeting_commitments(db, first)
    # Give the original a concrete date so a date change is detectable.
    original = _commitments(db)[0]
    original.due_at = datetime(2026, 10, 16, tzinfo=UTC)
    db.flush()

    second = _meeting(
        db, user.id, project.id, title="Standup", owner="Akhil",
        reassigned_from="Lokesh",
        transcript=(
            "Lokesh: I cannot make Friday, Akhil can you take the demo video?\n"
            "Akhil: Yes, I will have it by Monday instead."
        ),
    )
    replacement_rows = promisemirror.sync_meeting_commitments(db, second)
    assert replacement_rows["handoffs"] == 1

    findings = promisemirror.analyse(db, owner_user_id=user.id, project_id=project.id)
    kinds = {f.kind for f in findings}
    assert "handed_over" in kinds
