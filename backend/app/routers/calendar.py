"""Calendar connection and event-based bot scheduling."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user
from app.models import Calendar, User
from app.services.calendar import (
    CalendarError,
    RecallCalendarClient,
    build_authorization_url,
    exchange_code_for_tokens,
    fetch_google_email,
)
from app.services.recall import RecallError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calendar", tags=["calendar"])

# CSRF state for the OAuth round trip. In-process is fine for a single
# backend instance; move to Redis or the database before scaling out.
_PENDING_STATES: dict[str, tuple[datetime, str]] = {}
STATE_TTL = timedelta(minutes=10)


def _new_state(user_id: str) -> str:
    _prune_states()
    state = secrets.token_urlsafe(24)
    _PENDING_STATES[state] = (datetime.now(timezone.utc), user_id)
    return state


def _prune_states() -> None:
    cutoff = datetime.now(timezone.utc) - STATE_TTL
    for key, (created, _) in list(_PENDING_STATES.items()):
        if created < cutoff:
            _PENDING_STATES.pop(key, None)


def _consume_state(state: str) -> str | None:
    """Return the user who started this flow, or None if the state is bad."""
    _prune_states()
    entry = _PENDING_STATES.pop(state, None)
    return entry[1] if entry else None


@router.get("/oauth/start")
async def oauth_start(
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Return the Google consent URL for the frontend to open."""
    try:
        url = build_authorization_url(settings, _new_state(user.id))
    except CalendarError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"authorization_url": url}


@router.get("/oauth/callback")
async def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Google redirects here. Exchange the code and register with Recall."""
    frontend = settings.cors_origin_list[0] if settings.cors_origin_list else "/"

    def fail(reason: str) -> RedirectResponse:
        logger.warning("Calendar OAuth failed: %s", reason)
        return RedirectResponse(f"{frontend}/calendar?error={reason}", status_code=303)

    if error:
        return fail(error)
    if not code or not state:
        return fail("missing_code")
    owner_id = _consume_state(state)
    if not owner_id:
        # Unknown or expired state: treat as CSRF.
        return fail("invalid_state")

    try:
        tokens = await exchange_code_for_tokens(settings, code)
        email = await fetch_google_email(tokens.get("access_token", ""))

        client = RecallCalendarClient(settings)
        created = await client.create_calendar(
            oauth_client_id=settings.google_client_id or "",
            oauth_client_secret=settings.google_client_secret or "",
            oauth_refresh_token=tokens["refresh_token"],
            oauth_email=email,
        )
    except (CalendarError, RecallError) as exc:
        return fail("connect_failed")

    recall_id = created.get("id")

    # Reconnecting the same account: Recall mints a new calendar each time, so
    # retire the previous row for this email instead of stacking duplicates.
    if email:
        for stale in db.scalars(
            select(Calendar).where(
                Calendar.email == email,
                Calendar.owner_id == owner_id,
                Calendar.recall_calendar_id != recall_id,
            )
        ):
            try:
                await client.delete_calendar(stale.recall_calendar_id)
            except RecallError as exc:
                logger.warning(
                    "Could not delete superseded calendar %s: %s",
                    stale.recall_calendar_id,
                    exc,
                )
            db.delete(stale)
        db.flush()

    existing = db.scalar(select(Calendar).where(Calendar.recall_calendar_id == recall_id))
    if existing is None:
        db.add(
            Calendar(
                recall_calendar_id=recall_id,
                platform=created.get("platform", "google_calendar"),
                email=email,
                owner_id=owner_id,
                google_refresh_token=tokens["refresh_token"],
                status=(created.get("status") or {}).get("code")
                if isinstance(created.get("status"), dict)
                else created.get("status"),
            )
        )
        db.flush()
    else:
        # Reconnect with a fresh grant (e.g. after a scope change).
        existing.google_refresh_token = tokens["refresh_token"]
        db.flush()

    logger.info("Connected calendar %s for %s", recall_id, email)
    return RedirectResponse(f"{frontend}/calendar?connected=1", status_code=303)


@router.get("")
async def list_calendars(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(Calendar)
            .where(Calendar.owner_id == user.id)
            .order_by(Calendar.created_at.desc())
        )
    )

    # The row is written at creation time, when Recall still says "connecting".
    # Refresh any that have not reached a settled state.
    unsettled = [c for c in rows if c.status not in {"connected", "disconnected"}]
    if unsettled:
        client = RecallCalendarClient(settings)
        for calendar in unsettled:
            try:
                live = await client.get_calendar(calendar.recall_calendar_id)
            except RecallError as exc:
                logger.warning(
                    "Could not refresh calendar %s: %s", calendar.recall_calendar_id, exc
                )
                continue
            status_value = live.get("status")
            calendar.status = (
                status_value.get("code")
                if isinstance(status_value, dict)
                else status_value
            )
            if live.get("platform_email"):
                calendar.email = live["platform_email"]
        db.flush()

    return [
        {
            "id": c.id,
            "recall_calendar_id": c.recall_calendar_id,
            "platform": c.platform,
            "email": c.email,
            "status": c.status,
            "auto_record": c.auto_record,
        }
        for c in rows
    ]


@router.get("/{calendar_id}/events")
async def list_events(
    calendar_id: str,
    days_ahead: int = Query(default=7, ge=1, le=60),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    """Upcoming events, annotated with whether a bot is already scheduled."""
    calendar = db.get(Calendar, calendar_id)
    if calendar is None or calendar.owner_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown calendar {calendar_id}")

    now = datetime.now(timezone.utc)
    try:
        events = await RecallCalendarClient(settings).list_events(
            calendar.recall_calendar_id,
            start_time_gte=now.isoformat(),
            start_time_lte=(now + timedelta(days=days_ahead)).isoformat(),
        )
    except RecallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc.detail)
        ) from exc

    return [
        {
            "id": e.get("id"),
            "title": (e.get("raw") or {}).get("summary"),
            "start_time": e.get("start_time"),
            "end_time": e.get("end_time"),
            "meeting_url": e.get("meeting_url"),
            "meeting_platform": e.get("meeting_platform"),
            "is_deleted": e.get("is_deleted", False),
            "bot_scheduled": bool(e.get("bots")),
            "bots": e.get("bots") or [],
        }
        for e in events
    ]


@router.post("/events/{event_id}/schedule", status_code=status.HTTP_201_CREATED)
async def schedule_bot(
    event_id: str,
    user: User = Depends(current_user),
    consent_acknowledged: bool = Query(
        default=False,
        description="Must be true: the bot will record and transcribe this meeting.",
    ),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Schedule the notetaker for a calendar event."""
    if not consent_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "consent_acknowledged must be true. The bot records and transcribes "
                "the meeting; confirm participants are informed before scheduling."
            ),
        )

    try:
        event = await RecallCalendarClient(settings).schedule_bot(
            event_id,
            bot_name=settings.bot_name,
            deduplication_key=f"meetmind-{event_id}",
        )
    except RecallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc.detail)
        ) from exc

    return {"event_id": event_id, "bots": event.get("bots") or []}


@router.delete("/events/{event_id}/schedule")
async def unschedule_bot(
    event_id: str,
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    try:
        await RecallCalendarClient(settings).unschedule_bot(event_id)
    except RecallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc.detail)
        ) from exc
    return {"event_id": event_id, "scheduled": False}


@router.post("/deadlines/{deadline_id}/push", status_code=status.HTTP_201_CREATED)
async def push_deadline_to_calendar(
    deadline_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Create a Google Calendar event for an extracted deadline."""
    from app.models import Deadline
    from app.services.calendar import (
        create_all_day_event,
        ensure_meetmind_calendar,
        refresh_access_token,
    )

    deadline = db.get(Deadline, deadline_id)
    if deadline is None or deadline.meeting.owner_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown deadline {deadline_id}")

    if deadline.google_event_id:
        return {
            "deadline_id": deadline.id,
            "already_present": True,
            "google_event_id": deadline.google_event_id,
            "google_event_link": deadline.google_event_link,
        }

    if deadline.due_at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"This deadline has no resolvable date (spoken as "
                f"{deadline.when_text!r}), so it cannot be placed on a calendar."
            ),
        )

    calendar = db.scalar(
        select(Calendar)
        .where(
            Calendar.owner_id == user.id,
            Calendar.google_refresh_token.is_not(None),
        )
        .order_by(Calendar.created_at.desc())
    )
    if calendar is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No calendar is connected with write access. Connect Google "
                "Calendar (or reconnect it if you connected before write access "
                "was requested)."
            ),
        )

    meeting = deadline.meeting
    description = f"Deadline captured by MeetMind AI from: {meeting.title or meeting.meeting_url}"

    try:
        token = await refresh_access_token(settings, calendar.google_refresh_token)
        target_calendar = calendar.meetmind_calendar_id
        if not target_calendar:
            target_calendar = await ensure_meetmind_calendar(token)
            calendar.meetmind_calendar_id = target_calendar
            db.flush()
        event = await create_all_day_event(
            token,
            summary=deadline.what,
            date_iso=deadline.due_at.date().isoformat(),
            description=description,
            calendar_id=target_calendar,
        )
    except CalendarError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    deadline.google_event_id = event.get("id")
    deadline.google_event_link = event.get("htmlLink")
    deadline.google_calendar_id = target_calendar
    db.flush()

    return {
        "deadline_id": deadline.id,
        "already_present": False,
        "google_event_id": deadline.google_event_id,
        "google_event_link": deadline.google_event_link,
        "date": deadline.due_at.date().isoformat(),
    }


@router.delete("/deadlines/{deadline_id}/push")
async def remove_deadline_from_calendar(
    deadline_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    from app.models import Deadline
    from app.services.calendar import delete_event, refresh_access_token

    deadline = db.get(Deadline, deadline_id)
    if deadline is None or deadline.meeting.owner_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown deadline {deadline_id}")
    if not deadline.google_event_id:
        return {"deadline_id": deadline.id, "removed": False}

    calendar = db.scalar(
        select(Calendar).where(
            Calendar.owner_id == user.id, Calendar.google_refresh_token.is_not(None)
        )
    )
    if calendar is not None:
        try:
            token = await refresh_access_token(settings, calendar.google_refresh_token)
            await delete_event(
                token,
                deadline.google_event_id,
                deadline.google_calendar_id or "primary",
            )
        except CalendarError as exc:
            logger.warning("Could not delete Google event: %s", exc)

    deadline.google_event_id = None
    deadline.google_event_link = None
    deadline.google_calendar_id = None
    db.flush()
    return {"deadline_id": deadline.id, "removed": True}


@router.get("/deadlines")
async def list_deadlines(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[dict[str, Any]]:
    """Every extracted deadline across meetings, with its calendar state.

    Recall only syncs real meetings, so deadlines we push as all-day events do
    not come back through the calendar-events feed. This reads our own records
    instead, which is the authoritative source for what MeetMind extracted.
    """
    from app.models import Deadline

    from app.models import Meeting

    rows = db.scalars(
        select(Deadline)
        .join(Meeting, Deadline.meeting_id == Meeting.id)
        .where(Meeting.owner_id == user.id)
        .order_by(Deadline.due_at.is_(None), Deadline.due_at.asc())
    )
    return [
        {
            "id": d.id,
            "what": d.what,
            "when_text": d.when_text,
            "due_at": d.due_at.isoformat() if d.due_at else None,
            "on_calendar": bool(d.google_event_id),
            "google_event_link": d.google_event_link,
            "meeting_id": d.meeting_id,
            "meeting_title": d.meeting.title if d.meeting else None,
        }
        for d in rows
    ]
