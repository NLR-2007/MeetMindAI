"""Transcript retrieval and normalisation.

Verified against a real Recall recording: the transcript download returns a
JSON array of utterances, each shaped

    {"participant": {"id", "name", "is_host", "email", "platform", ...},
     "words": [{"text", "start_timestamp": {"relative", "absolute"}, ...}]}

The download URL is a pre-signed S3 link nested at
`recordings[].media_shortcuts.transcript.data.download_url`. It needs no auth
header and it expires, so never persist it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(90.0, connect=10.0)


@dataclass
class ParticipantInfo:
    recall_participant_id: str | None
    name: str | None
    email: str | None
    is_host: bool
    platform: str | None


@dataclass
class ParsedTranscript:
    plain_text: str
    utterances: list[dict[str, Any]]
    participants: list[ParticipantInfo] = field(default_factory=list)
    word_count: int = 0


def find_transcript_url(bot: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Return (download_url, recording_id, status_code) from a Bot object."""
    for recording in bot.get("recordings") or []:
        shortcuts = recording.get("media_shortcuts") or {}
        transcript = shortcuts.get("transcript") or {}
        status = (transcript.get("status") or {}).get("code")
        data = transcript.get("data") or {}
        url = data.get("download_url")
        if url:
            return url, recording.get("id"), status
    return None, None, None


def find_audio_url(bot: dict[str, Any]) -> str | None:
    """Pre-signed URL for the mixed audio, used only by the Whisper fallback."""
    for recording in bot.get("recordings") or []:
        shortcuts = recording.get("media_shortcuts") or {}
        for key in ("audio_mixed", "video_mixed"):
            data = (shortcuts.get(key) or {}).get("data") or {}
            if data.get("download_url"):
                return data["download_url"]
    return None


async def download_bytes(url: str, *, max_bytes: int = 24 * 1024 * 1024) -> bytes:
    """Fetch media for the Whisper fallback. Groq caps uploads around 25MB."""
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content = resp.content
    if len(content) > max_bytes:
        raise ValueError(
            f"Audio is {len(content) // 1_048_576}MB, above the {max_bytes // 1_048_576}MB "
            "limit for the Whisper fallback."
        )
    return content


async def download_transcript(url: str) -> list[dict[str, Any]]:
    """Fetch the pre-signed transcript JSON. No auth header is required."""
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, list):
        logger.warning("Unexpected transcript payload type: %s", type(payload).__name__)
        return []
    return payload


def parse_transcript(utterances: list[dict[str, Any]]) -> ParsedTranscript:
    """Flatten utterances into speaker-attributed text plus participant records."""
    lines: list[str] = []
    seen: dict[str, ParticipantInfo] = {}
    words_total = 0

    for utterance in utterances:
        participant = utterance.get("participant") or {}
        name = participant.get("name") or "Unknown speaker"
        pid = participant.get("id")
        pid_str = str(pid) if pid is not None else None

        words = utterance.get("words") or []
        words_total += len(words)
        text = " ".join(w.get("text", "") for w in words).strip()
        if text:
            lines.append(f"{name}: {text}")

        key = pid_str or name
        if key not in seen:
            seen[key] = ParticipantInfo(
                recall_participant_id=pid_str,
                name=participant.get("name"),
                email=participant.get("email"),
                is_host=bool(participant.get("is_host")),
                platform=participant.get("platform"),
            )

    return ParsedTranscript(
        plain_text="\n".join(lines),
        utterances=utterances,
        participants=list(seen.values()),
        word_count=words_total,
    )
