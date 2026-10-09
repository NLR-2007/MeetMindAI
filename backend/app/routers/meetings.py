"""Meeting endpoints: dispatch, status, history, detail, processing."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user, owned_meeting, readable_meeting
from app.models import Commitment, Meeting, Project, User
from app.schemas import (
    ActionItemOut,
    DeadlineOut,
    JoinMeetingRequest,
    MeetingDetailOut,
    MeetingOut,
    MeetingStatusOut,
    MeetingSummaryOut,
    ParticipantOut,
    ProcessResultOut,
    detect_platform,
)
from app.services import meeting_service
from app.services import teams as team_service
from app.services.recall import RecallClient, RecallError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/meetings", tags=["meetings"])

TERMINAL = {"done", "fatal"}


def get_recall(settings: Settings = Depends(get_settings)) -> RecallClient:
    return RecallClient(settings)


def _to_out(meeting: Meeting) -> MeetingOut:
    return MeetingOut(
        id=meeting.id,
        bot_id=meeting.bot_id,
        meeting_url=meeting.meeting_url,
        platform=meeting.platform,
        bot_name=meeting.bot_name,
        title=meeting.title,
        status=meeting.status,
        created_at=meeting.created_at,
        has_transcript=meeting.transcript is not None,
        has_summary=meeting.summary is not None,
        project_id=meeting.project_id,
        # Denormalised so a meeting list does not need one query per row.
        project_name=meeting.project.name if meeting.project else None,
        team_id=meeting.team_id,
        team_name=meeting.team.name if meeting.team else None,
    )


@router.post("/join", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def join_meeting(
    payload: JoinMeetingRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    recall: RecallClient = Depends(get_recall),
    user: User = Depends(current_user),
) -> MeetingOut:
    """Send the MeetMind AI Notetaker into a meeting."""
    platform = detect_platform(payload.meeting_url) or "unknown"
    bot_name = payload.bot_name or settings.bot_name

    # A team meeting is recorded once for everybody, so the caller must
    # actually be in the team they are recording for.
    if payload.team_id is not None and not team_service.is_member(
        db, payload.team_id, user
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown team {payload.team_id}",
        )

    # The whole point of a team is one bot per meeting. If a colleague has
    # already sent one to this URL and it is still live, join that recording
    # instead of putting a second bot in the room.
    if payload.team_id is not None:
        existing = db.scalars(
            select(Meeting)
            .where(
                Meeting.team_id == payload.team_id,
                Meeting.meeting_url == payload.meeting_url.strip(),
                Meeting.status.notin_(list(TERMINAL)),
            )
            .order_by(Meeting.created_at.desc())
        ).first()
        if existing is not None:
            logger.info(
                "Reusing live bot %s for team %s rather than dispatching a second",
                existing.bot_id,
                payload.team_id,
            )
            return _to_out(existing)

    # Filing a meeting under someone else's project would leak it into their
    # Mark Up context and their commitment history. 404 rather than 403, so an
    # id that is not yours is indistinguishable from one that does not exist.
    if payload.project_id is not None:
        project = db.get(Project, payload.project_id)
        if project is None or project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown project_id {payload.project_id}",
            )

    try:
        meeting = await meeting_service.dispatch_bot(
            db,
            settings,
            recall,
            meeting_url=payload.meeting_url,
            platform=platform,
            bot_name=bot_name,
            transcription=payload.transcription,
            title=payload.title,
            project_id=payload.project_id,
            owner_id=user.id,
        )
        if payload.team_id is not None:
            meeting.team_id = payload.team_id
            db.flush()
            db.refresh(meeting)
    except RecallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Recall.ai rejected the request ({exc.status_code}): {exc.detail}",
        ) from exc

    return _to_out(meeting)


@router.get("", response_model=list[MeetingOut])
async def list_meetings(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    limit: int = 50,
) -> list[MeetingOut]:
    """Meeting history, newest first. Cached status only; no upstream call."""
    rows = db.scalars(
        select(Meeting)
        # Every row reports its project name, so load them in one go rather
        # than firing a query per meeting.
        .options(selectinload(Meeting.project), selectinload(Meeting.team))
        # Own meetings plus team meetings recorded after joining.
        .where(team_service.visible_meetings_filter(db, user))
        .order_by(Meeting.created_at.desc())
        .limit(min(limit, 200))
    )
    return [_to_out(m) for m in rows]


@router.get("/{meeting_id}/status", response_model=MeetingStatusOut)
async def meeting_status(
    meeting: Meeting = Depends(readable_meeting),
    db: Session = Depends(get_db),
    recall: RecallClient = Depends(get_recall),
) -> MeetingStatusOut:
    try:
        await meeting_service.sync_status(db, recall, meeting)
    except RecallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not read bot status from Recall.ai: {exc.detail}",
        ) from exc

    return MeetingStatusOut(
        meeting_id=meeting.id,
        bot_id=meeting.bot_id,
        status=meeting.status,
        platform=meeting.platform,
        meeting_url=meeting.meeting_url,
        status_changes=meeting.status_changes or [],
        is_terminal=meeting.status in TERMINAL,
    )


@router.get("/{meeting_id}", response_model=MeetingDetailOut)
async def meeting_detail(
    include_transcript: bool = False,
    meeting: Meeting = Depends(readable_meeting),
) -> MeetingDetailOut:
    base = _to_out(meeting)
    return MeetingDetailOut(
        **base.model_dump(),
        status_changes=meeting.status_changes or [],
        participants=[ParticipantOut.model_validate(p) for p in meeting.participants],
        summary=(
            MeetingSummaryOut.model_validate(meeting.summary) if meeting.summary else None
        ),
        action_items=[ActionItemOut.model_validate(a) for a in meeting.action_items],
        deadlines=[DeadlineOut.model_validate(d) for d in meeting.deadlines],
        transcript_word_count=meeting.transcript.word_count if meeting.transcript else None,
        transcript_text=(
            meeting.transcript.plain_text
            if include_transcript and meeting.transcript
            else None
        ),
    )


class SetProjectRequest(BaseModel):
    # None files the meeting back under "no project".
    project_id: str | None = None


@router.patch("/{meeting_id}/project", response_model=MeetingOut)
async def set_meeting_project(
    payload: SetProjectRequest,
    meeting: Meeting = Depends(owned_meeting),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MeetingOut:
    """File an existing meeting under a project, or move it between projects.

    Meetings recorded before the project selector existed have no project, so
    without this they can never join a series. Commitments drawn from the
    meeting are re-pointed too: a promise belongs to the same project as the
    conversation it came from, and leaving them behind would split a project's
    history from its promises.
    """
    if payload.project_id is not None:
        project = db.get(Project, payload.project_id)
        if project is None or project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown project_id {payload.project_id}",
            )

    meeting.project_id = payload.project_id
    moved = db.scalars(
        select(Commitment).where(Commitment.source_meeting_id == meeting.id)
    ).all()
    for commitment in moved:
        commitment.project_id = payload.project_id
    db.flush()
    db.refresh(meeting)
    logger.info(
        "Meeting %s filed under project %s (%d commitment(s) moved)",
        meeting.id,
        payload.project_id,
        len(moved),
    )
    return _to_out(meeting)


@router.post("/{meeting_id}/process", response_model=ProcessResultOut)
async def process_meeting(
    force: bool = False,
    meeting: Meeting = Depends(owned_meeting),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    recall: RecallClient = Depends(get_recall),
) -> ProcessResultOut:
    """Pull the transcript and run Groq analysis. Safe to call repeatedly."""
    try:
        result = await meeting_service.process_completed_meeting(
            db, settings, recall, meeting, force=force
        )
    except RecallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Recall.ai error: {exc.detail}",
        ) from exc

    return ProcessResultOut(**result)


@router.post("/{meeting_id}/leave", response_model=MeetingStatusOut)
async def leave_meeting(
    meeting: Meeting = Depends(owned_meeting),
    db: Session = Depends(get_db),
    recall: RecallClient = Depends(get_recall),
) -> MeetingStatusOut:
    """Remove the bot from the call."""
    try:
        await recall.leave_call(meeting.bot_id)
        await meeting_service.sync_status(db, recall, meeting)
    except RecallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc.detail)
        ) from exc

    return MeetingStatusOut(
        meeting_id=meeting.id,
        bot_id=meeting.bot_id,
        status=meeting.status,
        platform=meeting.platform,
        meeting_url=meeting.meeting_url,
        status_changes=meeting.status_changes or [],
        is_terminal=meeting.status in TERMINAL,
    )


@router.delete("/{meeting_id}", status_code=status.HTTP_200_OK)
async def delete_meeting(
    meeting: Meeting = Depends(owned_meeting),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Permanently delete a meeting and everything derived from it.

    Transcript, summary, participants, action items, deadlines, chat history
    and coaching notes cascade with the row. Commitments sourced from this
    meeting are removed explicitly, since their foreign key only nulls out and
    would otherwise leave promises with no origin.

    The Hindsight memory bank for this meeting is dropped too: leaving it would
    mean the assistant still "remembers" a meeting the user deleted.

    Google Calendar events already created from its deadlines are NOT removed —
    they live in the user's own calendar and are theirs to keep or delete.
    """
    from app.models import CoachingNote, Commitment
    from app.services import memory as memory_module

    meeting_id = meeting.id
    title = meeting.title or meeting.meeting_url

    orphaned = list(
        db.scalars(select(Commitment).where(Commitment.source_meeting_id == meeting_id))
    )
    for commitment in orphaned:
        # Unlink supersession chains so no row points at a deleted commitment.
        if commitment.superseded_by_id:
            replacement = db.get(Commitment, commitment.superseded_by_id)
            if replacement is not None:
                replacement.supersedes_id = None
        db.delete(commitment)

    # Coaching notes have no ORM relationship on Meeting, so they would rely on
    # a database-level cascade. Delete them explicitly: private feedback must
    # not outlive the meeting it describes, on any backend.
    notes = list(
        db.scalars(select(CoachingNote).where(CoachingNote.meeting_id == meeting_id))
    )
    for note in notes:
        db.delete(note)

    calendar_events_kept = sum(1 for d in meeting.deadlines if d.google_event_id)

    db.delete(meeting)
    db.flush()

    memory_dropped = False
    if memory_module.hindsight_active():
        base = memory_module.hindsight_base_url()
        try:
            import httpx

            # Async client: a sync delete would block the event loop for up to
            # the full timeout if Hindsight is slow to answer.
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{base}/v1/default/banks/meeting-{meeting_id}"
                )
            memory_dropped = resp.status_code < 400
        except Exception:
            # The row is already gone; a stale bank is not worth failing on.
            logger.warning("Could not drop Hindsight bank for %s", meeting_id)

    logger.info("Deleted meeting %s (%s)", meeting_id, title)
    return {
        "deleted": True,
        "meeting_id": meeting_id,
        "title": title,
        "commitments_removed": len(orphaned),
        "coaching_notes_removed": len(notes),
        "memory_bank_dropped": memory_dropped,
        "calendar_events_kept": calendar_events_kept,
    }
