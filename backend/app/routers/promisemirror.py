"""PromiseMirror endpoints: commitments, findings and the timeline."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import Commitment, Meeting, User
from app.services import promisemirror, team

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/promisemirror", tags=["promisemirror"])


class CommitmentOut(BaseModel):
    id: str
    kind: str
    text: str
    owner_name: str | None = None
    status: str
    due_at: str | None = None
    due_text: str | None = None
    evidence: str | None = None
    meeting_id: str | None = None
    meeting_title: str | None = None
    project_id: str | None = None
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    confirmed: bool = True


class StatusUpdate(BaseModel):
    status: str = Field(pattern="^(pending|completed|cancelled)$")
    # A transcript hint is a suggestion, not an instruction: the user confirms.
    confirmed: bool = True


def _out(db: Session, c: Commitment) -> CommitmentOut:
    meeting = db.get(Meeting, c.source_meeting_id) if c.source_meeting_id else None
    return CommitmentOut(
        id=c.id,
        kind=c.kind,
        text=c.text,
        owner_name=c.owner_name,
        status=c.status,
        due_at=c.due_at.isoformat() if c.due_at else None,
        due_text=c.due_text,
        evidence=c.evidence,
        meeting_id=c.source_meeting_id,
        meeting_title=(meeting.title or meeting.meeting_url) if meeting else None,
        project_id=c.project_id,
        supersedes_id=c.supersedes_id,
        superseded_by_id=c.superseded_by_id,
        confirmed=c.confirmed,
    )


@router.get("/commitments", response_model=list[CommitmentOut])
def list_commitments(
    project_id: str | None = None,
    meeting_id: str | None = None,
    status_filter: str | None = None,
    assigned_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[CommitmentOut]:
    """Commitments the caller may see.

    Employees get only their own; managers also get their reports'.
    """
    # Personal view: a manager sees their own promises here, not the team's.
    stmt = select(Commitment).where(team.own_commitments_filter(user))
    if assigned_to:
        stmt = stmt.where(Commitment.assigned_user_id == assigned_to)
    if project_id:
        stmt = stmt.where(Commitment.project_id == project_id)
    if meeting_id:
        stmt = stmt.where(Commitment.source_meeting_id == meeting_id)
    if status_filter:
        stmt = stmt.where(Commitment.status == status_filter)
    rows = db.scalars(stmt.order_by(Commitment.due_at.is_(None), Commitment.due_at.asc()))
    return [_out(db, c) for c in rows]


@router.get("/findings")
def findings(
    project_id: str | None = None,
    meeting_id: str | None = None,
    assigned_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    results = promisemirror.analyse(
        db,
        owner_user_id=user.id,
        project_id=project_id,
        meeting_id=meeting_id,
        assigned_to=assigned_to,
        visible_user_ids=[user.id],
    )
    counts: dict[str, int] = {}
    for f in results:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    return {"count": len(results), "by_kind": counts, "findings": [f.as_dict() for f in results]}


@router.get("/timeline")
def commitment_timeline(
    project_id: str | None = None,
    meeting_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    return promisemirror.timeline(
        db,
        owner_user_id=user.id,
        project_id=project_id,
        meeting_id=meeting_id,
        visible_user_ids=[user.id],
    )


@router.post("/commitments/{commitment_id}/status", response_model=CommitmentOut)
def update_status(
    commitment_id: str,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CommitmentOut:
    """Manually set progress. Completion is always an explicit user action."""
    c = db.get(Commitment, commitment_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Unknown commitment {commitment_id}")
    if not team.can_modify(user, c):
        # Managers can read a report's commitment but never close it for them.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the person who owns this commitment can change its status.",
        )
    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Status changes must be confirmed by the user.",
        )

    c.status = payload.status
    c.completed_at = datetime.now(UTC) if payload.status == "completed" else None
    db.flush()
    return _out(db, c)


class ChangeResolution(BaseModel):
    # Which date actually stands. "original" is the one that was agreed out
    # loud; "new" accepts the quietly-changed one as a real decision.
    keep: str = Field(pattern="^(original|new)$")


@router.post("/commitments/{commitment_id}/resolve-change", response_model=CommitmentOut)
def resolve_change(
    commitment_id: str,
    payload: ChangeResolution,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CommitmentOut:
    """Settle a silently-changed deadline.

    `commitment_id` is the newer version. Keeping "new" records that the change
    was intended, which stops the alert. Keeping "original" reinstates the date
    that was actually agreed and cancels the version nobody announced.

    Either way the audit trail survives: nothing is deleted, only re-pointed.
    """
    replacement = db.get(Commitment, commitment_id)
    if replacement is None:
        raise HTTPException(status_code=404, detail=f"Unknown commitment {commitment_id}")
    if not team.can_modify(user, replacement):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the person who owns this commitment can resolve its date.",
        )
    original = (
        db.get(Commitment, replacement.supersedes_id)
        if replacement.supersedes_id
        else None
    )
    if original is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This commitment did not replace an earlier one, so there is nothing to resolve.",
        )

    if payload.keep == "new":
        replacement.confirmed = True
        resolved = replacement
    else:
        # The agreed date stands. The unannounced version is cancelled rather
        # than removed, so the record still shows that it was attempted.
        original.status = "pending"
        original.superseded_by_id = None
        original.confirmed = True
        replacement.status = "cancelled"
        replacement.confirmed = True
        resolved = original

    db.flush()
    logger.info(
        "Resolved silent change on %s: kept %s", commitment_id, payload.keep
    )
    return _out(db, resolved)


@router.post("/sync/{meeting_id}")
def sync_from_meeting(
    meeting_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Re-derive commitments from a processed meeting."""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or meeting.owner_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown meeting_id {meeting_id}")
    result = promisemirror.sync_meeting_commitments(db, meeting)
    # Map spoken names to real teammates so each person sees their own work.
    result.update(team.assign_commitments(db, user))
    return result
