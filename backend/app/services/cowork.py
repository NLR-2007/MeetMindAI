"""MeetMind Co-Work: shared progress, with ownership that cannot be faked.

Co-Work inverts the product's default on purpose. Everywhere else your
progress is private; here the people in the room can see each other's, because
work handed out between several people only coordinates if everyone can see
where it stands.

Two rules keep that from becoming surveillance:

* **Admission is a decision.** The link lets you ask. The space owner accepts
  or rejects. Having a URL is never enough, because being let in is what makes
  your progress visible.
* **Only the assignee closes their own work.** Not a teammate, not the owner.
  A board where anyone can mark anything done records what people assumed, not
  what happened — which is exactly the failure MeetMind exists to catch.
"""
from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CoWorkDeadlineChangeRequest,
    CoWorkJoinRequest,
    CoWorkMembership,
    CoWorkspace,
    CoWorkTask,
    User,
)

logger = logging.getLogger(__name__)

TOKEN_BYTES = 24
VALID_STATUS = ("todo", "in_progress", "done")
PENDING_DEADLINE_STATUS = "pending"


def create_workspace(
    db: Session, *, name: str, purpose: str | None, team_id: str | None, owner: User
) -> CoWorkspace:
    space = CoWorkspace(
        name=name.strip(),
        purpose=(purpose or "").strip() or None,
        team_id=team_id,
        owner_id=owner.id,
        join_token=secrets.token_urlsafe(TOKEN_BYTES),
    )
    db.add(space)
    db.flush()
    db.add(CoWorkMembership(workspace_id=space.id, user_id=owner.id, role="lead"))
    db.flush()
    db.refresh(space)
    return space


def membership(db: Session, workspace_id: str, user: User) -> CoWorkMembership | None:
    return db.scalars(
        select(CoWorkMembership).where(
            CoWorkMembership.workspace_id == workspace_id,
            CoWorkMembership.user_id == user.id,
        )
    ).first()


def is_member(db: Session, workspace_id: str, user: User) -> bool:
    return membership(db, workspace_id, user) is not None


def is_lead(db: Session, workspace_id: str, user: User) -> bool:
    """The Lead runs the door, not the board.

    They decide who gets in, and that is the whole of their authority. They
    cannot edit, move or close anyone else's work - over other people's tasks
    a Lead is strictly read-only, like everybody else.
    """
    m = membership(db, workspace_id, user)
    return m is not None and m.role == "lead"


def workspaces_for(db: Session, user: User) -> list[CoWorkspace]:
    rows = db.scalars(
        select(CoWorkMembership).where(CoWorkMembership.user_id == user.id)
    ).all()
    spaces = [m.workspace for m in rows if m.workspace is not None]
    return sorted(spaces, key=lambda s: s.name.lower())


# --- getting in -----------------------------------------------------------


def request_to_join(
    db: Session, *, token: str, user: User, note: str | None = None
) -> tuple[CoWorkspace | None, str | None, str]:
    """Ask to join. Returns (workspace, error, outcome).

    `outcome` is one of "member", "pending", "rejected" so the caller can say
    something accurate rather than a generic success.
    """
    space = db.scalars(
        select(CoWorkspace).where(CoWorkspace.join_token == token)
    ).first()
    if space is None:
        return None, "That Co-Work link is not valid.", "none"

    if is_member(db, space.id, user):
        return space, None, "member"

    existing = db.scalars(
        select(CoWorkJoinRequest).where(
            CoWorkJoinRequest.workspace_id == space.id,
            CoWorkJoinRequest.user_id == user.id,
        )
    ).first()
    if existing is not None:
        if existing.status == "pending":
            return space, None, "pending"
        if existing.status == "rejected":
            # Asking again after a rejection reopens the request rather than
            # being silently ignored; the owner decides again.
            existing.status = "pending"
            existing.note = note or existing.note
            existing.decided_by = None
            existing.decided_at = None
            db.flush()
            return space, None, "pending"

    db.add(
        CoWorkJoinRequest(workspace_id=space.id, user_id=user.id, note=note)
    )
    db.flush()
    logger.info("User %s asked to join co-work space %s", user.id, space.id)
    return space, None, "pending"


def decide_request(
    db: Session, *, request: CoWorkJoinRequest, approve: bool, decider: User
) -> None:
    request.status = "approved" if approve else "rejected"
    request.decided_by = decider.id
    request.decided_at = datetime.now(UTC)
    if approve and not is_member(db, request.workspace_id, request.user):
        db.add(
            CoWorkMembership(
                workspace_id=request.workspace_id,
                user_id=request.user_id,
                role="member",
            )
        )
    db.flush()
    logger.info(
        "Co-work request %s %s by %s",
        request.id,
        request.status,
        decider.id,
    )


# --- the rule that makes the board trustworthy ----------------------------


def owns_task(task: CoWorkTask, user: User) -> bool:
    """Is this person the one answerable for this task?

    The single gate for changing anything about a task: its status, its
    wording, who holds it, and whether it exists. Deliberately excludes the
    Lead. Someone else editing or closing your work turns the board into a
    record of what people assumed rather than what happened, which is the
    exact failure MeetMind exists to catch. An unassigned task has nobody to
    vouch for it, so it cannot be moved until somebody claims it.
    """
    return task.assignee_id is not None and task.assignee_id == user.id


def may_claim(task: CoWorkTask) -> bool:
    """Anyone in the room can pick up work nobody holds."""
    return task.assignee_id is None


def set_status(db: Session, *, task: CoWorkTask, status: str) -> CoWorkTask:
    task.status = status
    task.completed_at = datetime.now(UTC) if status == "done" else None
    db.flush()
    return task


def pending_deadline_request(
    db: Session, *, task_id: str
) -> CoWorkDeadlineChangeRequest | None:
    return db.scalars(
        select(CoWorkDeadlineChangeRequest).where(
            CoWorkDeadlineChangeRequest.task_id == task_id,
            CoWorkDeadlineChangeRequest.status == PENDING_DEADLINE_STATUS,
        )
    ).first()


def create_deadline_request(
    db: Session,
    *,
    task: CoWorkTask,
    requester: User,
    requested_due_at: datetime,
    reason: str | None = None,
) -> CoWorkDeadlineChangeRequest:
    req = CoWorkDeadlineChangeRequest(
        workspace_id=task.workspace_id,
        task_id=task.id,
        requester_id=requester.id,
        current_due_at=task.due_at,
        requested_due_at=requested_due_at,
        reason=(reason or "").strip() or None,
    )
    db.add(req)
    db.flush()
    logger.info(
        "User %s requested deadline change for co-work task %s",
        requester.id,
        task.id,
    )
    return req


def decide_deadline_request(
    db: Session,
    *,
    request: CoWorkDeadlineChangeRequest,
    approve: bool,
    decider: User,
) -> CoWorkDeadlineChangeRequest:
    request.status = "approved" if approve else "rejected"
    request.decided_by = decider.id
    request.decided_at = datetime.now(UTC)
    if approve:
        request.task.due_at = request.requested_due_at
    db.flush()
    logger.info(
        "Co-work deadline request %s %s by %s",
        request.id,
        request.status,
        decider.id,
    )
    return request


def release_tasks_of(db: Session, *, workspace_id: str, user_id: str) -> int:
    """Hand someone's tasks back to the board when they leave.

    Without this, a departed member's work can never be edited, closed or
    removed by anyone - the assignee-only rule would freeze it permanently.
    Unassigning keeps the task visible and claimable instead of deleting a
    record of what was outstanding.
    """
    orphaned = db.scalars(
        select(CoWorkTask).where(
            CoWorkTask.workspace_id == workspace_id,
            CoWorkTask.assignee_id == user_id,
        )
    ).all()
    for task in orphaned:
        task.assignee_id = None
    db.flush()
    return len(orphaned)


def progress_for(tasks: list[CoWorkTask]) -> dict[str, int]:
    done = sum(1 for t in tasks if t.status == "done")
    doing = sum(1 for t in tasks if t.status == "in_progress")
    return {
        "total": len(tasks),
        "done": done,
        "in_progress": doing,
        "todo": len(tasks) - done - doing,
        "percent": round(100 * done / len(tasks)) if tasks else 0,
    }
