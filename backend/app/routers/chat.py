"""Meeting-scoped chat.

Every answer is grounded in exactly one meeting's records. Switching to a
different meeting requires explicit confirmation so context never changes
silently underneath the user.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user, owned_meeting
from app.models import ChatMessage, Meeting, User
from app.schemas import ChatMessageOut, ChatRequest, ChatResponse
from app.services import meeting_service
from app.services.groq_client import GroqClient, GroqError
from app.services.memory import get_memory_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/meetings/{meeting_id}/chat", tags=["chat"])

HISTORY_TURNS = 8


@router.get("", response_model=list[ChatMessageOut])
async def chat_history(
    meeting: Meeting = Depends(owned_meeting),
    db: Session = Depends(get_db),
) -> list[ChatMessageOut]:
    meeting_id = meeting.id
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.meeting_id == meeting_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return [ChatMessageOut.model_validate(r) for r in rows]


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    meeting: Meeting = Depends(owned_meeting),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> ChatResponse:
    meeting_id = meeting.id

    if not settings.groq_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROQ_API_KEY is not configured; chat is unavailable.",
        )

    # If the question names a different meeting, ask before switching context.
    other = _referenced_other_meeting(db, payload.message, meeting_id, user.id)
    if other is not None and not payload.confirm_context_switch:
        return ChatResponse(
            meeting_id=meeting_id,
            answer=(
                f"That looks like a question about a different meeting "
                f"(\"{other.title or other.meeting_url}\"). I am currently answering "
                f"about \"{meeting.title or meeting.meeting_url}\". Confirm the switch "
                f"and I will use that meeting's records instead."
            ),
            context_switch_required=True,
            pending_meeting_id=other.id,
        )

    if meeting.transcript is None and meeting.summary is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This meeting has no transcript or summary yet. "
                f"Run POST /meetings/{meeting_id}/process first."
            ),
        )

    context = meeting_service.build_chat_context(meeting)

    memory = get_memory_service(db)
    recalled = memory.recall_memory(
        payload.message, scope="meeting", scope_id=meeting_id, limit=5
    )
    if recalled:
        joined = "\n".join(f"- {m['content']}" for m in recalled)
        context = f"{context}\n\nRecalled memories:\n{joined}"

    history_rows = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.meeting_id == meeting_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(HISTORY_TURNS)
        )
    )
    history = [
        {"role": m.role, "content": m.content} for m in reversed(history_rows)
    ]

    try:
        answer, tokens = await GroqClient(settings).answer_about_meeting(
            payload.message, context, history
        )
    except GroqError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Groq error: {exc.detail}"
        ) from exc

    db.add(ChatMessage(meeting_id=meeting_id, role="user", content=payload.message))
    db.add(ChatMessage(meeting_id=meeting_id, role="assistant", content=answer))
    db.flush()

    return ChatResponse(meeting_id=meeting_id, answer=answer, tokens_used=tokens)


def _referenced_other_meeting(db: Session, message: str, current_id: str, owner_id: str):
    """Detect a reference to another meeting the SAME user owns.

    Scoped by owner so a title belonging to someone else can never be named
    back to this caller.
    """
    lowered = message.lower()
    candidates = db.scalars(
        select(Meeting).where(Meeting.id != current_id, Meeting.owner_id == owner_id)
    )
    for other in candidates:
        if other.id.lower() in lowered:
            return other
        if other.title and len(other.title) > 4 and other.title.lower() in lowered:
            return other
    return None
