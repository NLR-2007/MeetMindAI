"""My Team — a manager's read-only view of their reports.

Everything here is deliberately read-only. A manager can see what their team
promised, what is overdue and what changed, but cannot mark anyone's work
complete: closing a commitment is the owner's statement about their own work.

Personal coaching notes are never exposed here, at any role.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import Commitment, Meeting, Project, User
from app.services import promisemirror, team as team_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/team", tags=["team"])


def manager_only(user: User = Depends(current_user)) -> User:
    if user.role != team_service.MANAGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only managers can view team data.",
        )
    return user


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("/overview")
def overview(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    manager: User = Depends(manager_only),
) -> dict[str, Any]:
    """Per-person rollup across the manager's reports."""
    now = datetime.now(timezone.utc)
    member_ids = team_service.team_user_ids(db, manager)
    members = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(member_ids)))
    }

    stmt = select(Commitment).where(
        team_service.visible_commitments_filter(db, manager)
    )
    if project_id:
        stmt = stmt.where(Commitment.project_id == project_id)
    commitments = list(db.scalars(stmt))

    rows: dict[str, dict[str, Any]] = {
        uid: {
            "user_id": uid,
            "name": u.name or u.email,
            "email": u.email,
            "role": u.role,
            "is_you": uid == manager.id,
            "total": 0,
            "pending": 0,
            "completed": 0,
            "overdue": 0,
            "next_due": None,
        }
        for uid, u in members.items()
    }
    unassigned = {
        "user_id": None,
        "name": "Unassigned",
        "email": "",
        "role": "",
        "is_you": False,
        "total": 0,
        "pending": 0,
        "completed": 0,
        "overdue": 0,
        "next_due": None,
    }

    for c in commitments:
        key = c.assigned_user_id if c.assigned_user_id in rows else None
        row = rows[key] if key else unassigned
        row["total"] += 1
        if c.status == "completed":
            row["completed"] += 1
        elif c.status == "pending":
            row["pending"] += 1
            due = _aware(c.due_at)
            if due:
                if due < now:
                    row["overdue"] += 1
                current = row["next_due"]
                if current is None or due.isoformat() < current:
                    row["next_due"] = due.isoformat()

    for row in list(rows.values()) + [unassigned]:
        row["percent"] = (
            round(100 * row["completed"] / row["total"]) if row["total"] else 0
        )

    members_out = sorted(
        rows.values(), key=lambda r: (not r["is_you"], r["name"].lower())
    )
    if unassigned["total"]:
        members_out.append(unassigned)

    return {
        "manager": {"id": manager.id, "name": manager.name or manager.email},
        "members": members_out,
        "totals": {
            "people": len(members),
            "pending": sum(r["pending"] for r in members_out),
            "completed": sum(r["completed"] for r in members_out),
            "overdue": sum(r["overdue"] for r in members_out),
        },
    }


@router.get("/commitments")
def team_commitments(
    member_id: str | None = None,
    project_id: str | None = None,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    manager: User = Depends(manager_only),
) -> list[dict[str, Any]]:
    """Every commitment across the team. Read-only."""
    member_ids = team_service.team_user_ids(db, manager)
    if member_id and member_id not in member_ids:
        raise HTTPException(status_code=404, detail="Unknown team member")

    stmt = select(Commitment).where(
        team_service.visible_commitments_filter(db, manager)
    )
    if member_id:
        stmt = stmt.where(Commitment.assigned_user_id == member_id)
    if project_id:
        stmt = stmt.where(Commitment.project_id == project_id)
    if status_filter:
        stmt = stmt.where(Commitment.status == status_filter)

    rows = list(
        db.scalars(stmt.order_by(Commitment.due_at.is_(None), Commitment.due_at.asc()))
    )
    people = {u.id: u for u in db.scalars(select(User).where(User.id.in_(member_ids)))}
    meetings = {
        m.id: m for m in db.scalars(select(Meeting).where(Meeting.owner_id.in_(member_ids)))
    }

    out = []
    for c in rows:
        person = people.get(c.assigned_user_id or "")
        meeting = meetings.get(c.source_meeting_id or "")
        due = _aware(c.due_at)
        out.append(
            {
                "id": c.id,
                "kind": c.kind,
                "text": c.text,
                "status": c.status,
                "spoken_owner": c.owner_name,
                "assigned_to": person.name or person.email if person else None,
                "assigned_user_id": c.assigned_user_id,
                "due_at": due.isoformat() if due else None,
                "due_text": c.due_text,
                "evidence": c.evidence,
                "meeting_id": c.source_meeting_id,
                "meeting_title": (meeting.title or meeting.meeting_url) if meeting else None,
                "superseded_by_id": c.superseded_by_id,
                "supersedes_id": c.supersedes_id,
            }
        )
    return out


@router.get("/deadlines")
def team_deadlines(
    days_ahead: int = 30,
    db: Session = Depends(get_db),
    manager: User = Depends(manager_only),
) -> dict[str, Any]:
    """Dated, still-open commitments across the team, split by urgency."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)
    member_ids = team_service.team_user_ids(db, manager)
    people = {u.id: u for u in db.scalars(select(User).where(User.id.in_(member_ids)))}

    rows = db.scalars(
        select(Commitment).where(
            team_service.visible_commitments_filter(db, manager),
            Commitment.status == "pending",
            Commitment.due_at.is_not(None),
        )
    )

    overdue: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    for c in rows:
        due = _aware(c.due_at)
        if due is None:
            continue
        person = people.get(c.assigned_user_id or "")
        item = {
            "id": c.id,
            "text": c.text,
            "due_at": due.isoformat(),
            "assigned_to": person.name or person.email if person else "Unassigned",
            "assigned_user_id": c.assigned_user_id,
            "meeting_id": c.source_meeting_id,
        }
        if due < now:
            overdue.append(item)
        elif due <= horizon:
            upcoming.append(item)

    overdue.sort(key=lambda i: i["due_at"])
    upcoming.sort(key=lambda i: i["due_at"])
    return {"overdue": overdue, "upcoming": upcoming}


@router.get("/findings")
def team_findings(
    project_id: str | None = None,
    member_id: str | None = None,
    db: Session = Depends(get_db),
    manager: User = Depends(manager_only),
) -> dict[str, Any]:
    """PromiseMirror across the team: changed decisions, clashes, gaps."""
    member_ids = team_service.team_user_ids(db, manager)
    if member_id and member_id not in member_ids:
        raise HTTPException(status_code=404, detail="Unknown team member")

    results = promisemirror.analyse(
        db,
        owner_user_id=manager.id,
        project_id=project_id,
        assigned_to=member_id,
        visible_user_ids=member_ids,
    )
    counts: dict[str, int] = {}
    for f in results:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    return {
        "count": len(results),
        "by_kind": counts,
        "findings": [f.as_dict() for f in results],
    }


@router.get("/projects")
def team_projects(
    db: Session = Depends(get_db), manager: User = Depends(manager_only)
) -> list[dict[str, Any]]:
    """Project rollup across everyone the manager can see."""
    member_ids = team_service.team_user_ids(db, manager)
    projects = {
        p.id: p
        for p in db.scalars(select(Project).where(Project.owner_id.in_(member_ids)))
    }
    commitments = list(
        db.scalars(
            select(Commitment).where(
                team_service.visible_commitments_filter(db, manager)
            )
        )
    )

    rollup: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for c in commitments:
        key = c.project_id or "unassigned"
        row = rollup.setdefault(
            key,
            {
                "project_id": c.project_id,
                "project_name": projects[key].name if key in projects else "Unassigned",
                "total": 0,
                "completed": 0,
                "pending": 0,
                "overdue": 0,
            },
        )
        row["total"] += 1
        if c.status == "completed":
            row["completed"] += 1
        elif c.status == "pending":
            row["pending"] += 1
            due = _aware(c.due_at)
            if due and due < now:
                row["overdue"] += 1

    for row in rollup.values():
        row["percent"] = (
            round(100 * row["completed"] / row["total"]) if row["total"] else 0
        )
    return sorted(rollup.values(), key=lambda r: -r["total"])
