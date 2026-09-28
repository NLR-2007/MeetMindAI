"""PromiseMirror: personal commitment intelligence.

Turns a meeting's extracted action items, deadlines and decisions into durable
`Commitment` rows, then compares them against everything already promised in
the same project.

Two principles run through this module:

* **Nothing is overwritten.** When a deadline moves, the original commitment is
  kept and marked `superseded`, with the replacement linked both ways. The
  history of a promise is the point of the feature.
* **Every finding cites its source.** A finding without a meeting and a
  transcript excerpt behind it is an opinion, so findings carry both.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import ActionItem, Commitment, Deadline, Meeting, Summary

logger = logging.getLogger(__name__)

APPROACHING_DAYS = 3
# Two commitments are "the same promise" above this word-overlap ratio.
SIMILARITY_THRESHOLD = 0.6


def _normalise(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    # Drop filler so "record the demo video" ~ "record demo video".
    stop = {"the", "a", "an", "to", "of", "for", "and", "will", "be", "is", "on", "by", "in"}
    return {w for w in words if w not in stop and len(w) > 2}


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of content words. Cheap, deterministic, explainable."""
    sa, sb = _normalise(a), _normalise(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class Finding:
    kind: str
    severity: str  # high | medium | low
    title: str
    detail: str
    commitment_id: str | None = None
    meeting_id: str | None = None
    meeting_title: str | None = None
    evidence: str | None = None
    due_at: str | None = None
    related: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "commitment_id": self.commitment_id,
            "meeting_id": self.meeting_id,
            "meeting_title": self.meeting_title,
            "evidence": self.evidence,
            "due_at": self.due_at,
            "related": self.related,
        }


def _excerpt(meeting: Meeting, needle: str, width: int = 240) -> str | None:
    """Find the transcript line a commitment most likely came from."""
    if not meeting.transcript or not meeting.transcript.plain_text:
        return None
    text = meeting.transcript.plain_text
    terms = _normalise(needle)
    best, best_score = None, 0.0
    for line in text.splitlines():
        score = similarity(line, needle)
        if score > best_score:
            best, best_score = line, score
    if best and best_score > 0.15:
        return best[:width]
    # Fall back to the first line mentioning any distinctive term.
    for line in text.splitlines():
        if any(t in line.lower() for t in terms):
            return line[:width]
    return None


def sync_meeting_commitments(db: Session, meeting: Meeting) -> dict[str, int]:
    """Create or update commitments from one processed meeting.

    Idempotent: re-running after re-analysis updates in place rather than
    duplicating, and records supersession when a date has moved.
    """
    if meeting.owner_id is None:
        logger.warning("Meeting %s has no owner; skipping commitments", meeting.id)
        return {"created": 0, "superseded": 0, "unchanged": 0}

    created = superseded = unchanged = 0

    # Everything already promised in this project, by this user.
    prior = list(
        db.scalars(
            select(Commitment).where(
                Commitment.owner_user_id == meeting.owner_id,
                Commitment.project_id == meeting.project_id,
                Commitment.status.in_(["pending", "completed"]),
            )
        )
    )

    incoming: list[dict[str, Any]] = []
    for item in meeting.action_items:
        incoming.append(
            {
                "kind": "promise",
                "text": item.task,
                "owner_name": item.owner_name,
                "due_at": None,
                "due_text": item.due_text,
            }
        )
    for deadline in meeting.deadlines:
        incoming.append(
            {
                "kind": "promise",
                "text": deadline.what,
                "owner_name": None,
                "due_at": deadline.due_at,
                "due_text": deadline.when_text,
            }
        )
    if meeting.summary and meeting.summary.decisions:
        for decision in meeting.summary.decisions:
            incoming.append(
                {
                    "kind": "decision",
                    "text": decision,
                    "owner_name": None,
                    "due_at": None,
                    "due_text": None,
                }
            )

    for row in incoming:
        text = (row["text"] or "").strip()
        if not text:
            continue

        match = None
        for candidate in prior:
            if candidate.kind != row["kind"]:
                continue
            if similarity(candidate.text, text) >= SIMILARITY_THRESHOLD:
                match = candidate
                break

        evidence = _excerpt(meeting, text)

        if match is None:
            db.add(
                Commitment(
                    owner_user_id=meeting.owner_id,
                    project_id=meeting.project_id,
                    source_meeting_id=meeting.id,
                    kind=row["kind"],
                    text=text,
                    owner_name=row["owner_name"],
                    due_at=row["due_at"],
                    due_text=row["due_text"],
                    evidence=evidence,
                )
            )
            created += 1
            continue

        # Same promise seen again. Did anything material change?
        date_changed = (
            row["due_at"] is not None
            and match.due_at is not None
            and row["due_at"].date() != match.due_at.date()
        )
        if match.source_meeting_id == meeting.id:
            # Re-analysis of the same meeting: update in place, no supersession.
            match.owner_name = row["owner_name"] or match.owner_name
            match.due_at = row["due_at"] or match.due_at
            match.due_text = row["due_text"] or match.due_text
            match.evidence = evidence or match.evidence
            unchanged += 1
        elif date_changed:
            replacement = Commitment(
                owner_user_id=meeting.owner_id,
                project_id=meeting.project_id,
                source_meeting_id=meeting.id,
                kind=row["kind"],
                text=text,
                owner_name=row["owner_name"] or match.owner_name,
                due_at=row["due_at"],
                due_text=row["due_text"],
                evidence=evidence,
                supersedes_id=match.id,
            )
            db.add(replacement)
            db.flush()
            # The original is kept, not edited: that is the audit trail.
            match.status = "superseded"
            match.superseded_by_id = replacement.id
            superseded += 1
        else:
            unchanged += 1

    db.flush()
    return {"created": created, "superseded": superseded, "unchanged": unchanged}


def analyse(
    db: Session,
    *,
    owner_user_id: str,
    project_id: str | None = None,
    meeting_id: str | None = None,
    visible_user_ids: list[str] | None = None,
    assigned_to: str | None = None,
    now: datetime | None = None,
) -> list[Finding]:
    """PromiseMirror findings, scoped to what the caller may see.

    `visible_user_ids` is the team scope: one id for an employee, several for a
    manager. Without it, only the caller's own commitments are considered.
    """
    now = now or datetime.now(timezone.utc)
    scope = visible_user_ids or [owner_user_id]
    stmt = select(Commitment).where(
        or_(
            Commitment.owner_user_id.in_(scope),
            Commitment.assigned_user_id.in_(scope),
        )
    )
    if assigned_to:
        stmt = stmt.where(Commitment.assigned_user_id == assigned_to)
    if project_id:
        stmt = stmt.where(Commitment.project_id == project_id)
    if meeting_id:
        stmt = stmt.where(Commitment.source_meeting_id == meeting_id)
    commitments = list(db.scalars(stmt.order_by(Commitment.created_at.asc())))

    findings: list[Finding] = []
    meetings = {
        m.id: m
        for m in db.scalars(select(Meeting).where(Meeting.owner_id.in_(scope)))
    }

    def meeting_title(cid: str | None) -> str | None:
        m = meetings.get(cid or "")
        return (m.title or m.meeting_url) if m else None

    pending = [c for c in commitments if c.status == "pending"]

    # 1. Overdue and 2. approaching.
    for c in pending:
        if not c.due_at:
            continue
        due = c.due_at if c.due_at.tzinfo else c.due_at.replace(tzinfo=timezone.utc)
        if due < now:
            findings.append(
                Finding(
                    kind="overdue",
                    severity="high",
                    title=f"Overdue: {c.text}",
                    detail=f"Was due {due.date().isoformat()} and is still pending.",
                    commitment_id=c.id,
                    meeting_id=c.source_meeting_id,
                    meeting_title=meeting_title(c.source_meeting_id),
                    evidence=c.evidence,
                    due_at=due.isoformat(),
                )
            )
        elif due <= now + timedelta(days=APPROACHING_DAYS):
            days = (due.date() - now.date()).days
            findings.append(
                Finding(
                    kind="approaching",
                    severity="medium",
                    title=f"Due in {days} day(s): {c.text}",
                    detail=f"Due {due.date().isoformat()}.",
                    commitment_id=c.id,
                    meeting_id=c.source_meeting_id,
                    meeting_title=meeting_title(c.source_meeting_id),
                    evidence=c.evidence,
                    due_at=due.isoformat(),
                )
            )

    # 3. Pending with no date at all.
    for c in pending:
        if c.due_at is None and c.kind == "promise":
            findings.append(
                Finding(
                    kind="undated",
                    severity="low",
                    title=f"No deadline agreed: {c.text}",
                    detail="This commitment has no date, so nothing will chase it.",
                    commitment_id=c.id,
                    meeting_id=c.source_meeting_id,
                    meeting_title=meeting_title(c.source_meeting_id),
                    evidence=c.evidence,
                )
            )

    # 4. No confirmed owner.
    for c in pending:
        if c.kind == "promise" and not c.owner_name:
            findings.append(
                Finding(
                    kind="unowned",
                    severity="medium",
                    title=f"Nobody owns: {c.text}",
                    detail="No owner was named, so this may fall through.",
                    commitment_id=c.id,
                    meeting_id=c.source_meeting_id,
                    meeting_title=meeting_title(c.source_meeting_id),
                    evidence=c.evidence,
                )
            )

    # 5. Changed decisions, with the original preserved.
    for c in commitments:
        if c.status == "superseded" and c.superseded_by_id:
            replacement = db.get(Commitment, c.superseded_by_id)
            if replacement is None:
                continue
            old = c.due_at.date().isoformat() if c.due_at else (c.due_text or "unset")
            new = (
                replacement.due_at.date().isoformat()
                if replacement.due_at
                else (replacement.due_text or "unset")
            )
            findings.append(
                Finding(
                    kind="changed",
                    severity="medium",
                    title=f"Changed: {c.text}",
                    detail=f"Moved from {old} to {new}.",
                    commitment_id=replacement.id,
                    meeting_id=replacement.source_meeting_id,
                    meeting_title=meeting_title(replacement.source_meeting_id),
                    evidence=replacement.evidence,
                    due_at=replacement.due_at.isoformat() if replacement.due_at else None,
                    related=[
                        {
                            "commitment_id": c.id,
                            "role": "original",
                            "meeting_id": c.source_meeting_id,
                            "meeting_title": meeting_title(c.source_meeting_id),
                            "due_at": c.due_at.isoformat() if c.due_at else None,
                            "evidence": c.evidence,
                        }
                    ],
                )
            )

    # 6. Two live promises on the same day that look like different work.
    by_date: dict[str, list[Commitment]] = {}
    for c in pending:
        if c.due_at:
            by_date.setdefault(c.due_at.date().isoformat(), []).append(c)
    for day, group in by_date.items():
        if len(group) < 2:
            continue
        findings.append(
            Finding(
                kind="conflicting",
                severity="medium",
                title=f"{len(group)} commitments all due {day}",
                detail="; ".join(c.text for c in group),
                meeting_id=group[0].source_meeting_id,
                meeting_title=meeting_title(group[0].source_meeting_id),
                due_at=f"{day}T00:00:00+00:00",
                related=[
                    {"commitment_id": c.id, "role": "conflict", "text": c.text}
                    for c in group
                ],
            )
        )

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f.severity, 3), f.due_at or "9999"))
    return findings


def timeline(
    db: Session,
    *,
    owner_user_id: str,
    project_id: str | None = None,
    meeting_id: str | None = None,
    visible_user_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Chronological history of every commitment: made, updated, completed."""
    scope = visible_user_ids or [owner_user_id]
    stmt = select(Commitment).where(
        or_(
            Commitment.owner_user_id.in_(scope),
            Commitment.assigned_user_id.in_(scope),
        )
    )
    if project_id:
        stmt = stmt.where(Commitment.project_id == project_id)
    if meeting_id:
        stmt = stmt.where(Commitment.source_meeting_id == meeting_id)
    rows = list(db.scalars(stmt.order_by(Commitment.created_at.asc())))

    events: list[dict[str, Any]] = []
    for c in rows:
        events.append(
            {
                "at": c.created_at.isoformat(),
                "event": "superseded_by" if c.supersedes_id else "made",
                "commitment_id": c.id,
                "text": c.text,
                "status": c.status,
                "owner_name": c.owner_name,
                "due_at": c.due_at.isoformat() if c.due_at else None,
                "meeting_id": c.source_meeting_id,
                "supersedes_id": c.supersedes_id,
                "evidence": c.evidence,
            }
        )
        if c.completed_at:
            events.append(
                {
                    "at": c.completed_at.isoformat(),
                    "event": "completed",
                    "commitment_id": c.id,
                    "text": c.text,
                    "status": "completed",
                    "meeting_id": c.source_meeting_id,
                }
            )
    events.sort(key=lambda e: e["at"])
    return events
