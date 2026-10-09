"""Priority inbox: the handful of senders that matter, and their promises.

Mail is a second source for PromiseMirror, not a mail client. A commitment
made in an email joins the same ledger as one made in a meeting, so a date
agreed in a call and quietly changed in a reply trips the same alarm.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user
from app.models import Calendar, Commitment, InboundEmail, PrioritySender, User
from app.services import mailbox
from app.services.calendar import CalendarError, refresh_access_token
from app.services.meeting_service import resolve_due_date

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inbox", tags=["inbox"])


class SenderIn(BaseModel):
    pattern: str = Field(min_length=3, max_length=255)
    label: str | None = Field(default=None, max_length=255)

    @field_validator("pattern")
    @classmethod
    def _clean(cls, v: str) -> str:
        p = v.strip().lower().lstrip("@")
        if " " in p or "." not in p:
            raise ValueError(
                "Enter an email address (ravi@acme.com) or a domain (acme.com)."
            )
        return p


class SenderOut(BaseModel):
    id: str
    pattern: str
    label: str | None


class EmailOut(BaseModel):
    id: str
    sender: str
    sender_name: str | None
    subject: str | None
    received_at: str | None
    matched_pattern: str | None
    summary: str | None
    highlights: list[str]
    urgent: bool
    urgency_reason: str | None
    read: bool


def _sender_out(s: PrioritySender) -> SenderOut:
    return SenderOut(id=s.id, pattern=s.pattern, label=s.label)


def _email_out(e: InboundEmail) -> EmailOut:
    return EmailOut(
        id=e.id,
        sender=e.sender,
        sender_name=e.sender_name,
        subject=e.subject,
        received_at=e.received_at.isoformat() if e.received_at else None,
        matched_pattern=e.matched_pattern,
        summary=e.summary,
        highlights=list(e.highlights or []),
        urgent=e.urgent,
        urgency_reason=e.urgency_reason,
        read=e.read,
    )


# --- who counts -----------------------------------------------------------


@router.get("/senders", response_model=list[SenderOut])
def list_senders(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[SenderOut]:
    rows = db.scalars(
        select(PrioritySender)
        .where(PrioritySender.owner_id == user.id)
        .order_by(PrioritySender.pattern)
    )
    return [_sender_out(s) for s in rows]


@router.post("/senders", response_model=SenderOut, status_code=201)
def add_sender(
    payload: SenderIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> SenderOut:
    existing = db.scalars(
        select(PrioritySender).where(
            PrioritySender.owner_id == user.id,
            PrioritySender.pattern == payload.pattern,
        )
    ).first()
    if existing is not None:
        # Adding the same sender twice is a no-op, not an error.
        return _sender_out(existing)
    sender = PrioritySender(
        owner_id=user.id, pattern=payload.pattern, label=payload.label
    )
    db.add(sender)
    db.flush()
    return _sender_out(sender)


@router.delete("/senders/{sender_id}", status_code=200)
def remove_sender(
    sender_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    sender = db.get(PrioritySender, sender_id)
    if sender is None or sender.owner_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown sender {sender_id}")
    db.delete(sender)
    db.flush()
    return {"deleted": True}


# --- the mail itself ------------------------------------------------------


@router.get("", response_model=list[EmailOut])
def list_mail(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[EmailOut]:
    stmt = select(InboundEmail).where(InboundEmail.owner_id == user.id)
    if unread_only:
        stmt = stmt.where(InboundEmail.read.is_(False))
    rows = db.scalars(
        # Urgent first, then newest: the whole point is not having to scan.
        stmt.order_by(InboundEmail.urgent.desc(), InboundEmail.received_at.desc())
    )
    return [_email_out(e) for e in rows]


@router.post("/{email_id}/read", response_model=EmailOut)
def mark_read(
    email_id: str,
    read: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> EmailOut:
    email = db.get(InboundEmail, email_id)
    if email is None or email.owner_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown email {email_id}")
    email.read = read
    db.flush()
    return _email_out(email)


@router.post("/sync")
async def sync_inbox(
    days: int = 14,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Pull recent mail from priority senders and understand it.

    Reuses the Google connection made for Calendar rather than asking for a
    second authorisation. Only messages from named senders are requested, and
    message bodies are never written to the database.
    """
    patterns = [
        s.pattern
        for s in db.scalars(
            select(PrioritySender).where(PrioritySender.owner_id == user.id)
        )
    ]
    if not patterns:
        return {
            "synced": 0,
            "new": 0,
            "commitments": 0,
            "message": "Add a priority sender first - nothing is read until you do.",
        }

    calendar = db.scalars(
        select(Calendar).where(
            Calendar.owner_id == user.id, Calendar.google_refresh_token.is_not(None)
        )
    ).first()
    if calendar is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Connect Google Calendar first: mail reuses that connection "
                "rather than asking you to authorise Google twice."
            ),
        )

    try:
        token = await refresh_access_token(settings, calendar.google_refresh_token)
    except CalendarError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        fetched = await mailbox.fetch_priority_mail(token, patterns=patterns, days=days)
    except mailbox.MailboxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    seen = {
        row
        for row in db.scalars(
            select(InboundEmail.gmail_id).where(InboundEmail.owner_id == user.id)
        )
    }

    created = 0
    promises = 0
    for item in fetched:
        if item.gmail_id in seen:
            continue
        understanding = await mailbox.understand(settings, item)
        email = InboundEmail(
            owner_id=user.id,
            gmail_id=item.gmail_id,
            thread_id=item.thread_id,
            sender=item.sender,
            sender_name=item.sender_name,
            subject=item.subject,
            received_at=(
                item.received_at.replace(tzinfo=None) if item.received_at else None
            ),
            matched_pattern=item.matched_pattern,
            summary=understanding.get("summary"),
            highlights=list(understanding.get("highlights") or [])[:4],
            urgent=bool(understanding.get("urgent")),
            urgency_reason=understanding.get("urgency_reason"),
        )
        db.add(email)
        created += 1

        anchor = item.received_at or datetime.now(UTC)
        for row in understanding.get("commitments") or []:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            # Same ledger as meetings, so a date changed between a call and a
            # reply is one commitment moving, not two unrelated records.
            db.add(
                Commitment(
                    owner_user_id=user.id,
                    kind="promise",
                    text=text,
                    owner_name=row.get("owner"),
                    due_at=resolve_due_date(
                        row.get("due_date"), row.get("due"), anchor
                    ),
                    due_text=row.get("due"),
                    evidence=f"Email from {item.sender}: {item.subject or ''}".strip(),
                )
            )
            promises += 1

    db.flush()
    logger.info(
        "Inbox sync for %s: %d fetched, %d new, %d commitments",
        user.id,
        len(fetched),
        created,
        promises,
    )
    return {
        "synced": len(fetched),
        "new": created,
        "commitments": promises,
        "message": None,
    }
