"""Recall.ai webhook receivers.

Signature verification follows
https://docs.recall.ai/docs/authenticating-requests-from-recallai

Recall signs with HMAC via Svix. Current workspaces send `Webhook-Id`,
`Webhook-Timestamp` and `Webhook-Signature`; workspaces created before
2025-12-15 send the `svix-*` equivalents. The Svix library accepts both.

Headers are only sent once a workspace verification secret (whsec_...) exists.
Create one at: Developers > API Keys & Secrets > Create Workspace Secret.
If RECALL_WEBHOOK_SECRET is unset, this module REFUSES to accept webhooks
unless ALLOW_UNVERIFIED_WEBHOOKS is explicitly enabled for local development.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Transcript
from app.services import meeting_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Status codes that mean the recording is finished and worth processing.
COMPLETION_EVENTS = {"bot.done", "recording.done", "transcript.done"}


def _verify(request: Request, body: bytes, settings: Settings) -> None:
    """Raise 401 unless the payload carries a valid Recall signature."""
    if not settings.recall_webhook_secret:
        if settings.allow_unverified_webhooks:
            logger.warning(
                "Accepting UNVERIFIED webhook: no RECALL_WEBHOOK_SECRET set. "
                "Never do this outside local development."
            )
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Webhook verification is not configured. Set RECALL_WEBHOOK_SECRET "
                "to your workspace secret (whsec_...)."
            ),
        )

    try:
        from svix.webhooks import Webhook, WebhookVerificationError
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="svix is not installed") from exc

    # Svix reads Webhook-Id/Timestamp/Signature and the legacy svix-* aliases.
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        Webhook(settings.recall_webhook_secret).verify(body, headers)
    except WebhookVerificationError as exc:
        logger.warning("Rejected webhook with bad signature: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature"
        ) from exc


def _extract_bot_id(payload: dict[str, Any]) -> str | None:
    """Bot id placement varies by event type."""
    data = payload.get("data") or {}
    for candidate in (
        data.get("bot_id"),
        (data.get("bot") or {}).get("id") if isinstance(data.get("bot"), dict) else None,
        (data.get("recording") or {}).get("bot_id")
        if isinstance(data.get("recording"), dict)
        else None,
        payload.get("bot_id"),
    ):
        if candidate:
            return str(candidate)
    return None


@router.post("/recall", status_code=status.HTTP_200_OK)
async def recall_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Status-change and completion events configured in the Recall dashboard."""
    body = await request.body()
    _verify(request, body, settings)

    payload = await request.json()
    event = payload.get("event") or payload.get("type") or "unknown"
    bot_id = _extract_bot_id(payload)
    logger.info("Recall webhook: event=%s bot=%s", event, bot_id)

    if not bot_id:
        # Acknowledge so Recall stops retrying an event we cannot route.
        return {"ok": True, "handled": False, "reason": "no bot id in payload"}

    meeting = meeting_service.get_meeting_by_bot(db, bot_id)
    if meeting is None:
        return {"ok": True, "handled": False, "reason": f"unknown bot {bot_id}"}

    # Keep the stored status current for any status-change event.
    status_code = ((payload.get("data") or {}).get("status") or {}).get("code")
    if status_code:
        meeting.status = status_code
        db.flush()

    handled = False
    if event in COMPLETION_EVENTS or status_code == "done":
        from app.services.recall import RecallClient

        try:
            result = await meeting_service.process_completed_meeting(
                db, settings, RecallClient(settings), meeting
            )
            handled = True
            logger.info("Processed meeting %s from webhook: %s", meeting.id, result)
        except Exception:
            # Never 500 at Recall: that triggers retries of work already partly done.
            logger.exception("Post-meeting processing failed for %s", meeting.id)

    return {"ok": True, "handled": handled, "meeting_id": meeting.id, "event": event}


@router.post("/recall/realtime", status_code=status.HTTP_200_OK)
async def recall_realtime_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Per-bot real-time events (transcript.data) sent during the call.

    These are dispatched directly to the URL given in the Create Bot request
    and cannot be configured in the dashboard.
    """
    body = await request.body()
    _verify(request, body, settings)

    payload = await request.json()
    event = payload.get("event") or "unknown"
    logger.debug("Realtime event: %s", event)
    if event != "transcript.data":
        return {"ok": True, "event": event, "handled": False}

    bot_id = _extract_bot_id(payload)
    meeting = meeting_service.get_meeting_by_bot(db, bot_id) if bot_id else None
    if meeting is None:
        return {"ok": True, "event": event, "handled": False}

    event_data = ((payload.get("data") or {}).get("data") or {})
    words = event_data.get("words") or []
    text = " ".join(
        str(word.get("text") or "").strip()
        for word in words
        if str(word.get("text") or "").strip()
    ).strip()
    if not text:
        return {"ok": True, "event": event, "handled": False}

    participant = event_data.get("participant") or {}
    utterance = {
        "participant_id": str(participant.get("id") or ""),
        "participant_name": participant.get("name"),
        "participant_email": participant.get("email"),
        "text": text,
        "start": ((words[0].get("start_timestamp") or {}).get("relative") if words else None),
        "end": ((words[-1].get("end_timestamp") or {}).get("relative") if words else None),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    transcript = meeting.transcript
    if transcript is None:
        transcript = Transcript(
            meeting_id=meeting.id,
            source="recall_realtime",
            plain_text="",
            utterances=[],
            word_count=0,
        )
        db.add(transcript)
    utterances = list(transcript.utterances or [])
    utterances.append(utterance)
    transcript.utterances = utterances[-500:]
    speaker = participant.get("name") or "Speaker"
    transcript.plain_text = f"{transcript.plain_text or ''}\n{speaker}: {text}".strip()
    transcript.word_count = (transcript.word_count or 0) + len(text.split())
    db.flush()
    return {"ok": True, "event": event, "handled": True, "meeting_id": meeting.id}
