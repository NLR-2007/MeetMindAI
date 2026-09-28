"""Meeting endpoints: dispatch, status, history, detail, processing."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user, owned_meeting
from app.models import Meeting, User
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
        .where(Meeting.owner_id == user.id)
        .order_by(Meeting.created_at.desc())
        .limit(min(limit, 200))
    )
    return [_to_out(m) for m in rows]


@router.get("/{meeting_id}/status", response_model=MeetingStatusOut)
async def meeting_status(
    meeting: Meeting = Depends(owned_meeting),
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
    meeting: Meeting = Depends(owned_meeting),
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
