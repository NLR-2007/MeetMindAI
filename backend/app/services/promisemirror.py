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
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Commitment, Meeting, Project

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
    # Which project this belongs to. Filled in once for every finding at the
    # end of analyse(), rather than at each of the seven places one is built.
    project_id: str | None = None
    project_name: str | None = None
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
            "project_id": self.project_id,
            "project_name": self.project_name,
            "related": self.related,
        }


_SEGMENT = re.compile(r"[.!?\r\n]+")

# Words people use when they are openly revising a date. Their absence is
# what makes a change "silent".
CHANGE_LANGUAGE = (
    "moved", "move", "changed", "change", "instead", "postponed", "postpone",
    "delayed", "delay", "pushed", "push", "revised", "revise", "rescheduled",
    "reschedule", "extended", "extend", "slipped", "brought forward",
    "earlier we said", "previously", "used to be", "no longer", "updated",
    "update", "new deadline", "new date",
)


def change_was_announced(transcript_text: str | None, commitment_text: str) -> bool:
    """Did anyone actually say the date was changing?

    A revision stated out loud is a decision. The same promise restated with a
    different date and no mention of the change is the dangerous case: everyone
    leaves the room believing a different thing. We look for change language in
    the lines that discuss this commitment, not anywhere in the meeting, so an
    unrelated "we moved the venue" cannot excuse a silent date shift.
    """
    if not transcript_text:
        return False

    terms = _normalise(commitment_text)
    if not terms:
        return False
    # Sentence-level, not line-level: a transcript may arrive as one block per
    # speaker, and "we moved the all-hands" sitting in the same paragraph must
    # not excuse a date shift two sentences later.
    for segment in _SEGMENT.split(transcript_text):
        lowered = segment.lower()
        if not any(word in lowered for word in CHANGE_LANGUAGE):
            continue
        # The change language has to be in a segment that is actually about
        # this commitment.
        overlap = len(terms & _normalise(segment)) / len(terms)
        if overlap >= 0.5:
            return True
    return False


def _owner_changed(before: str | None, after: str | None) -> bool:
    """Did this promise actually change hands?

    Only a real move counts. Extraction returning no owner for a promise that
    already had one usually means this meeting simply did not restate it, so
    that is "no change" rather than silently orphaning someone's promise. A
    genuine giving-up is signalled by reassigned_from, handled separately.
    """
    if not after:
        return False
    if not before:
        return True
    a, b = before.strip().lower(), after.strip().lower()
    if a == b:
        return False
    # "Bunny" and "Bunny Reddy" are the same person, not a handoff.
    return not (a in b or b in a)


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
        return {
            "created": 0,
            "superseded": 0,
            "unchanged": 0,
            "silent_changes": 0,
            "handoffs": 0,
        }

    created = superseded = unchanged = silent = handoffs = 0

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
                "reassigned_from": item.reassigned_from,
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
                "reassigned_from": None,
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
                    "reassigned_from": None,
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
                    reassigned_from=row.get("reassigned_from"),
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
        # Who owns a promise matters as much as when it is due. A later
        # meeting naming a different owner is a handoff, and the original
        # holder must stop carrying it.
        owner_changed = _owner_changed(match.owner_name, row["owner_name"])
        # "I'm busy, can someone take this?" with no taker. A null owner on
        # its own is ambiguous - it usually just means this meeting did not
        # restate who owns it - so only reassigned_from makes it a release.
        released = row.get("reassigned_from") is not None and not row["owner_name"]
        if match.source_meeting_id == meeting.id:
            # Re-analysis of the same meeting: update in place, no supersession.
            match.owner_name = None if released else (row["owner_name"] or match.owner_name)
            match.reassigned_from = row.get("reassigned_from") or match.reassigned_from
            match.due_at = row["due_at"] or match.due_at
            match.due_text = row["due_text"] or match.due_text
            match.evidence = evidence or match.evidence
            unchanged += 1
        elif date_changed or owner_changed or released:
            # A date that moved without anyone saying so is the case worth
            # shouting about: it is how teams end up with two "agreed" dates.
            announced = change_was_announced(
                meeting.transcript.plain_text if meeting.transcript else None, text
            )
            # Only a DATE that moved unannounced is "silent". A change of
            # owner is explicit by nature: someone had to say it out loud for
            # it to be extracted at all.
            silent_date_move = date_changed and not announced
            replacement = Commitment(
                owner_user_id=meeting.owner_id,
                project_id=meeting.project_id,
                source_meeting_id=meeting.id,
                kind=row["kind"],
                text=text,
                # A release clears the owner on purpose; otherwise a missing
                # owner means "not restated here", so the old one stands.
                owner_name=(
                    None
                    if released
                    else (
                        row["owner_name"]
                        if owner_changed
                        else (row["owner_name"] or match.owner_name)
                    )
                ),
                reassigned_from=(
                    row.get("reassigned_from")
                    or (match.owner_name if owner_changed else None)
                ),
                due_at=row["due_at"],
                due_text=row["due_text"],
                evidence=evidence,
                supersedes_id=match.id,
                confirmed=not silent_date_move,
            )
            db.add(replacement)
            db.flush()
            # The original is kept, not edited: that is the audit trail.
            match.status = "superseded"
            match.superseded_by_id = replacement.id
            superseded += 1
            if silent_date_move:
                silent += 1
            if owner_changed or released:
                handoffs += 1
        else:
            unchanged += 1

    db.flush()
    return {
        "created": created,
        "superseded": superseded,
        "unchanged": unchanged,
        "silent_changes": silent,
        "handoffs": handoffs,
    }


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
    now = now or datetime.now(UTC)
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
        # A change is a PAIR: the original from an earlier meeting and the
        # replacement from this one. Filtering on source_meeting_id alone
        # drops the original, so the pair is never whole and a silent date
        # change vanishes from any per-meeting view. Pull in whatever this
        # meeting superseded too. Those rows are "superseded", never
        # "pending", so they contribute no other findings.
        superseded_here = select(Commitment.id).where(
            Commitment.source_meeting_id == meeting_id
        )
        stmt = stmt.where(
            or_(
                Commitment.source_meeting_id == meeting_id,
                Commitment.superseded_by_id.in_(superseded_here),
            )
        )
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
        due = c.due_at if c.due_at.tzinfo else c.due_at.replace(tzinfo=UTC)
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
        if c.kind == "promise" and not c.owner_name and c.reassigned_from:
            # Someone put this down and nobody picked it up. That is not the
            # same as a task that never had an owner: there was a person who
            # expected to be relieved of it, and they may believe they were.
            findings.append(
                Finding(
                    kind="released",
                    severity="high",
                    title=f"Dropped by {c.reassigned_from}, nobody picked it up: {c.text}",
                    detail=(
                        f"{c.reassigned_from} handed this off and no one took it on. "
                        "It currently has no owner, so it will be missed unless "
                        "someone claims it."
                    ),
                    commitment_id=c.id,
                    meeting_id=c.source_meeting_id,
                    meeting_title=meeting_title(c.source_meeting_id),
                    evidence=c.evidence,
                    due_at=c.due_at.isoformat() if c.due_at else None,
                )
            )
            continue
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
            # A change nobody announced is the one that costs people their
            # deadlines: two meetings, two "agreed" dates, no decision between
            # them. Say which date was actually agreed and where.
            silent = not replacement.confirmed
            # A promise that changed hands is reported as a handoff, not as a
            # date change: who carries it is the thing that moved.
            handed_over = bool(replacement.reassigned_from) and _owner_changed(
                c.owner_name, replacement.owner_name
            )
            dropped = bool(replacement.reassigned_from) and not replacement.owner_name
            if silent:
                kind, severity = "silent_change", "high"
                title = f"Deadline moved without being agreed: {c.text}"
                detail = (
                    f"This was agreed as {old} in "
                    f"{meeting_title(c.source_meeting_id) or 'an earlier meeting'}. "
                    f"{meeting_title(replacement.source_meeting_id) or 'A later meeting'} "
                    f"treated it as {new}, and no one said it had changed. "
                    f"Unless someone decides otherwise, the agreed date is {old}."
                )
            elif dropped:
                # The "released" finding above already shouts about this; here
                # it only needs to explain the supersession in the history.
                kind, severity = "handed_over", "medium"
                title = f"No longer owned by {replacement.reassigned_from}: {c.text}"
                detail = (
                    f"{replacement.reassigned_from} gave this up in "
                    f"{meeting_title(replacement.source_meeting_id) or 'a later meeting'} "
                    "and nobody took it on."
                )
            elif handed_over:
                kind, severity = "handed_over", "medium"
                title = f"Handed over: {c.text}"
                detail = (
                    f"{replacement.reassigned_from} was carrying this; "
                    f"{replacement.owner_name} took it on in "
                    f"{meeting_title(replacement.source_meeting_id) or 'a later meeting'}."
                    + (f" Due {new}." if new != "unset" else "")
                )
            else:
                kind, severity = "changed", "medium"
                title = f"Changed: {c.text}"
                detail = f"Moved from {old} to {new}."
            findings.append(
                Finding(
                    kind=kind,
                    severity=severity,
                    title=title,
                    detail=detail,
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

    # Attribute every finding to a project, so the UI can group by workstream.
    # A commitment carries the project directly; when a finding only names a
    # meeting, the meeting's project stands in.
    project_of_commitment = {c.id: c.project_id for c in commitments}
    project_of_meeting = {m.id: m.project_id for m in meetings.values()}
    wanted = {
        pid
        for pid in (*project_of_commitment.values(), *project_of_meeting.values())
        if pid
    }
    project_names = (
        {
            p.id: p.name
            for p in db.scalars(select(Project).where(Project.id.in_(wanted)))
        }
        if wanted
        else {}
    )
    for f in findings:
        pid = project_of_commitment.get(f.commitment_id or "") or project_of_meeting.get(
            f.meeting_id or ""
        )
        f.project_id = pid
        f.project_name = project_names.get(pid or "") if pid else None

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
