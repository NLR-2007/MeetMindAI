"""Meeting orchestration: dispatch bots, sync status, process finished meetings."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    ActionItem,
    Deadline,
    Meeting,
    Participant,
    Summary,
    Transcript,
)
from app.services.groq_client import GroqClient, GroqError
from app.services.memory import get_memory_service
from app.services.recall import RecallClient, latest_status
from app.services.transcripts import (
    ParsedTranscript,
    download_bytes,
    download_transcript,
    find_audio_url,
    find_transcript_url,
    parse_transcript,
)

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"done", "fatal"}


def get_meeting(db: Session, meeting_id: str) -> Meeting | None:
    return db.get(Meeting, meeting_id)


def get_meeting_by_bot(db: Session, bot_id: str) -> Meeting | None:
    return db.scalar(select(Meeting).where(Meeting.bot_id == bot_id))


async def dispatch_bot(
    db: Session,
    settings: Settings,
    recall: RecallClient,
    *,
    meeting_url: str,
    platform: str,
    bot_name: str,
    transcription: bool,
    title: str | None = None,
    project_id: str | None = None,
    owner_id: str | None = None,
) -> Meeting:
    """Create the Recall bot and persist the meeting row."""
    realtime_url = None
    if settings.public_base_url:
        realtime_url = f"{settings.public_base_url.rstrip('/')}/webhooks/recall/realtime"

    bot = await recall.create_bot(
        meeting_url=meeting_url,
        bot_name=bot_name,
        transcription=transcription,
        realtime_webhook_url=realtime_url,
    )

    meeting = Meeting(
        bot_id=bot["id"],
        meeting_url=meeting_url,
        platform=platform,
        bot_name=bot_name,
        title=title,
        project_id=project_id,
        owner_id=owner_id,
        status=latest_status(bot),
        status_changes=bot.get("status_changes") or [],
        consent_acknowledged=True,
    )
    db.add(meeting)
    db.flush()
    logger.info("Dispatched bot %s to %s meeting %s", bot["id"], platform, meeting.id)
    return meeting


async def sync_status(db: Session, recall: RecallClient, meeting: Meeting) -> Meeting:
    """Refresh a meeting row from the live Recall bot object."""
    bot = await recall.get_bot(meeting.bot_id)
    meeting.status = latest_status(bot)
    meeting.status_changes = bot.get("status_changes") or []

    _, recording_id, _ = find_transcript_url(bot)
    if recording_id:
        meeting.recording_id = recording_id

    db.flush()
    return meeting


async def process_completed_meeting(
    db: Session,
    settings: Settings,
    recall: RecallClient,
    meeting: Meeting,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Retrieve the transcript, analyse it with Groq, and store the results.

    Idempotent: re-running without `force` skips work already done.
    """
    result: dict[str, Any] = {
        "meeting_id": meeting.id,
        "transcript_saved": False,
        "analysis_saved": False,
        "skipped_reason": None,
    }

    if meeting.transcript is not None and meeting.summary is not None and not force:
        result["skipped_reason"] = "already processed"
        return result

    bot = await recall.get_bot(meeting.bot_id)
    meeting.status = latest_status(bot)
    meeting.status_changes = bot.get("status_changes") or []

    url, recording_id, transcript_status = find_transcript_url(bot)
    if recording_id:
        meeting.recording_id = recording_id

    source = "recallai_streaming"

    if url:
        raw = await download_transcript(url)
        parsed = parse_transcript(raw)
    else:
        # Whisper fallback: Recall produced no transcript, but audio exists.
        # This yields plain text only — no speaker names, no word timestamps.
        fallback = await _whisper_fallback(settings, bot)
        if fallback is None:
            result["skipped_reason"] = (
                f"no transcript available yet (status={transcript_status}) "
                "and no audio to fall back on"
            )
            db.flush()
            return result
        parsed, source = fallback
        result["used_whisper_fallback"] = True

    # --- transcript ---
    transcript = meeting.transcript
    if transcript is None:
        transcript = Transcript(meeting_id=meeting.id)
        db.add(transcript)
    transcript.source = source
    transcript.plain_text = parsed.plain_text
    transcript.utterances = parsed.utterances
    transcript.word_count = parsed.word_count
    result["transcript_saved"] = True
    result["word_count"] = parsed.word_count

    # --- participants ---
    existing = {p.recall_participant_id for p in meeting.participants}
    for info in parsed.participants:
        if info.recall_participant_id in existing:
            continue
        db.add(
            Participant(
                meeting_id=meeting.id,
                recall_participant_id=info.recall_participant_id,
                name=info.name,
                email=info.email,
                is_host=info.is_host,
                platform=info.platform,
            )
        )
    result["participants"] = len(parsed.participants)

    # --- LLM analysis ---
    if not settings.groq_api_key:
        result["skipped_reason"] = "GROQ_API_KEY not configured; transcript saved only"
        db.flush()
        return result

    try:
        analysis_anchor = meeting.started_at or meeting.created_at
        if analysis_anchor.tzinfo is None:
            analysis_anchor = analysis_anchor.replace(tzinfo=timezone.utc)
        # Platform-supplied names are spelled correctly; the transcript's are not.
        known_names = [p.name for p in parsed.participants if p.name]
        analysis, tokens = await GroqClient(settings).analyse_meeting(
            parsed.plain_text,
            meeting_date=analysis_anchor.date().isoformat(),
            participants=known_names or None,
        )
    except GroqError as exc:
        # A failed summary must not lose the transcript we just stored.
        logger.error("Groq analysis failed for meeting %s: %s", meeting.id, exc)
        result["skipped_reason"] = f"analysis failed: {exc}"
        db.flush()
        return result

    summary = meeting.summary
    if summary is None:
        summary = Summary(meeting_id=meeting.id)
        db.add(summary)
    summary.summary_text = analysis["summary"]
    summary.decisions = analysis["decisions"]
    summary.model = settings.groq_model
    summary.tokens_used = tokens

    # Replace derived rows rather than accumulating duplicates on reprocess.
    # Deadlines already pushed to Google must keep their event link, or
    # re-analysis silently orphans real calendar events.
    pushed_links: dict[str, tuple[str | None, str | None]] = {}
    for deadline in list(meeting.deadlines):
        if deadline.google_event_id:
            pushed_links[_deadline_key(deadline.what, deadline.due_at)] = (
                deadline.google_event_id,
                deadline.google_event_link,
            )
        db.delete(deadline)
    for item in list(meeting.action_items):
        db.delete(item)
    db.flush()

    for item in analysis["action_items"]:
        db.add(
            ActionItem(
                meeting_id=meeting.id,
                task=item.get("task") or "",
                owner_name=item.get("owner"),
                due_text=item.get("due"),
            )
        )
    for deadline in analysis["deadlines"]:
        what = deadline.get("what") or ""
        due_at = resolve_due_date(
            deadline.get("date"), deadline.get("when"), analysis_anchor
        )
        event_id, event_link = pushed_links.pop(
            _deadline_key(what, due_at), (None, None)
        )
        db.add(
            Deadline(
                meeting_id=meeting.id,
                what=what,
                when_text=deadline.get("when"),
                due_at=due_at,
                google_event_id=event_id,
                google_event_link=event_link,
            )
        )

    if pushed_links:
        # Re-analysis dropped or reworded a deadline that had a calendar event.
        logger.warning(
            "Meeting %s: %d pushed deadline(s) no longer matched after "
            "re-analysis; their Google events are now orphaned: %s",
            meeting.id,
            len(pushed_links),
            [eid for eid, _ in pushed_links.values()],
        )

    # --- memory ---
    memory = get_memory_service(db)
    if analysis["summary"]:
        memory.save_memory(
            analysis["summary"],
            scope="meeting",
            scope_id=meeting.id,
            metadata={"kind": "summary", "model": settings.groq_model},
        )
    for decision in analysis["decisions"]:
        memory.save_memory(
            decision, scope="meeting", scope_id=meeting.id, metadata={"kind": "decision"}
        )

    # Commitments belong in memory too: without them, questions like
    # "who is writing the docs?" can only be answered from the raw transcript.
    for item in analysis["action_items"]:
        task = (item.get("task") or "").strip()
        if not task:
            continue
        owner = item.get("owner") or "someone unassigned"
        due = item.get("due") or item.get("due_date")
        sentence = f"{owner} will {task}" + (f", due {due}." if due else ".")
        memory.save_memory(
            sentence,
            scope="meeting",
            scope_id=meeting.id,
            metadata={"kind": "action_item"},
        )
    for deadline in analysis["deadlines"]:
        what = (deadline.get("what") or "").strip()
        if not what:
            continue
        when = deadline.get("date") or deadline.get("when")
        sentence = f"Deadline: {what}" + (f" on {when}." if when else ".")
        memory.save_memory(
            sentence,
            scope="meeting",
            scope_id=meeting.id,
            metadata={"kind": "deadline"},
        )

    # PromiseMirror: turn this meeting's extractions into durable commitments.
    try:
        from app.services import promisemirror

        # The action items and deadlines above were added to the session but the
        # relationships still hold the pre-delete state; expire them so the sync
        # sees what was actually just written.
        db.flush()
        db.refresh(meeting)
        result["commitments"] = promisemirror.sync_meeting_commitments(db, meeting)
    except Exception:
        # Commitment tracking must never cost us the analysis we just stored.
        logger.exception("Commitment sync failed for meeting %s", meeting.id)

    result["analysis_saved"] = True
    result["tokens_used"] = tokens
    result["action_items"] = len(analysis["action_items"])
    result["deadlines"] = len(analysis["deadlines"])
    db.flush()
    return result


def _deadline_key(what: str, due_at: datetime | None) -> str:
    """Identity for matching a deadline across re-analysis runs."""
    date_part = due_at.date().isoformat() if due_at else "nodate"
    return f"{(what or '').strip().lower()}|{date_part}"


def _parse_iso_date(value: str | None) -> datetime | None:
    """Strict ISO YYYY-MM-DD only."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def resolve_due_date(
    iso_value: str | None, spoken: str | None, anchor: datetime
) -> datetime | None:
    """Work out the calendar date a deadline refers to.

    The model is asked for an ISO date, but it is unreliable at date
    arithmetic, so its answer is only the first choice. When it declines (or
    returns nonsense) the spoken wording is parsed deterministically against
    the meeting date, which is what actually makes "3rd of October" resolvable.

    A date that lands before the meeting is rolled forward a year, on the
    reading that a deadline is a future commitment.
    """
    parsed = _parse_iso_date(iso_value)
    if parsed is not None:
        return parsed

    if not spoken:
        return None

    from dateutil import parser as date_parser

    try:
        parsed = date_parser.parse(
            spoken,
            fuzzy=True,
            default=anchor.replace(hour=0, minute=0, second=0, microsecond=0),
        )
    except (ValueError, OverflowError, TypeError):
        logger.debug("Could not resolve spoken date %r", spoken)
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    # Vague phrases ("soon") fuzzy-parse straight back to the anchor; that is
    # not a real date, so treat it as unresolved.
    if parsed.date() == anchor.date() and not any(ch.isdigit() for ch in spoken):
        return None

    if parsed.date() < anchor.date():
        try:
            parsed = parsed.replace(year=parsed.year + 1)
        except ValueError:  # 29 Feb
            parsed = parsed.replace(year=parsed.year + 1, day=28)

    return parsed


async def _whisper_fallback(
    settings: Settings, bot: dict[str, Any]
) -> tuple[ParsedTranscript, str] | None:
    """Transcribe the recording audio with Groq Whisper.

    Only reached when Recall has no transcript (transcription disabled, or the
    provider failed). Returns plain text with no speaker attribution.
    """
    if not settings.groq_api_key:
        return None

    audio_url = find_audio_url(bot)
    if not audio_url:
        return None

    try:
        audio = await download_bytes(audio_url)
        text = await GroqClient(settings).transcribe_audio(audio)
    except (GroqError, ValueError, httpx.HTTPError) as exc:
        logger.error("Whisper fallback failed: %s", exc)
        return None

    if not text.strip():
        return None

    logger.info("Used Whisper fallback (%d chars)", len(text))
    return (
        ParsedTranscript(
            plain_text=text.strip(),
            utterances=[],
            participants=[],
            word_count=len(text.split()),
        ),
        "whisper_fallback",
    )


def build_chat_context(meeting: Meeting, *, max_chars: int = 24_000) -> str:
    """Assemble the context for meeting-scoped chat. Only this meeting's data."""
    parts: list[str] = [
        f"Meeting: {meeting.title or meeting.meeting_url}",
        f"Platform: {meeting.platform}",
        f"Status: {meeting.status}",
    ]

    if meeting.participants:
        names = ", ".join(p.name or "Unknown" for p in meeting.participants)
        parts.append(f"Participants: {names}")

    if meeting.summary:
        parts.append(f"\nSummary:\n{meeting.summary.summary_text}")
        if meeting.summary.decisions:
            joined = "\n".join(f"- {d}" for d in meeting.summary.decisions)
            parts.append(f"\nDecisions:\n{joined}")

    if meeting.action_items:
        joined = "\n".join(
            f"- {a.task} (owner: {a.owner_name or 'unassigned'}, due: {a.due_text or 'n/a'})"
            for a in meeting.action_items
        )
        parts.append(f"\nAction items:\n{joined}")

    if meeting.deadlines:
        joined = "\n".join(f"- {d.what}: {d.when_text or 'n/a'}" for d in meeting.deadlines)
        parts.append(f"\nDeadlines:\n{joined}")

    if meeting.transcript and meeting.transcript.plain_text:
        text = meeting.transcript.plain_text
        budget = max_chars - sum(len(p) for p in parts)
        if budget > 500:
            # Keep the tail: later discussion usually carries the conclusions.
            clipped = text[-budget:]
            prefix = "\nTranscript (truncated):\n" if len(clipped) < len(text) else "\nTranscript:\n"
            parts.append(prefix + clipped)

    return "\n".join(parts)
