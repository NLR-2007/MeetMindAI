"""Request/response models for the MeetMind AI API."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Supported meeting platforms and the URL shapes Recall accepts.
MEETING_URL_PATTERNS: dict[str, re.Pattern[str]] = {
    "google_meet": re.compile(
        r"^https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}(\?.*)?$", re.I
    ),
    "zoom": re.compile(r"^https://([a-z0-9-]+\.)?zoom\.us/[jw]/\d+", re.I),
    "teams": re.compile(r"^https://teams\.(microsoft|live)\.com/", re.I),
}


def detect_platform(url: str) -> str | None:
    for platform, pattern in MEETING_URL_PATTERNS.items():
        if pattern.match(url):
            return platform
    return None


class JoinMeetingRequest(BaseModel):
    meeting_url: str = Field(
        description="Full meeting link, e.g. https://meet.google.com/abc-defg-hij"
    )
    bot_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=512)
    project_id: str | None = None
    # Recording consent is a hard gate, not a convenience flag (see README).
    consent_acknowledged: bool = Field(
        description=(
            "Must be true: the caller confirms all participants are told the bot "
            "records and transcribes."
        )
    )
    transcription: bool = True

    @field_validator("meeting_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = v.strip()
        if detect_platform(v) is None:
            raise ValueError(
                "Unrecognised meeting URL. Expected a Google Meet "
                "(https://meet.google.com/abc-defg-hij), Zoom, or Teams link."
            )
        return v

    @field_validator("consent_acknowledged")
    @classmethod
    def _require_consent(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError(
                "consent_acknowledged must be true. The bot records and transcribes "
                "the meeting; confirm participants are informed before joining."
            )
        return v


class MeetingSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    summary_text: str | None = None
    decisions: list[str] = []
    model: str | None = None
    tokens_used: int | None = None


class ActionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task: str
    owner_name: str | None = None
    due_text: str | None = None
    done: bool = False


class DeadlineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    what: str
    when_text: str | None = None
    due_at: datetime | None = None
    google_event_id: str | None = None
    google_event_link: str | None = None


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None = None
    email: str | None = None
    is_host: bool = False


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bot_id: str
    meeting_url: str
    platform: str
    bot_name: str
    title: str | None = None
    status: str | None = None
    created_at: datetime
    has_transcript: bool = False
    has_summary: bool = False


class MeetingDetailOut(MeetingOut):
    status_changes: list[dict[str, Any]] = []
    participants: list[ParticipantOut] = []
    summary: MeetingSummaryOut | None = None
    action_items: list[ActionItemOut] = []
    deadlines: list[DeadlineOut] = []
    transcript_word_count: int | None = None
    transcript_text: str | None = None


class MeetingStatusOut(BaseModel):
    meeting_id: str
    bot_id: str
    status: str | None
    platform: str
    meeting_url: str
    status_changes: list[dict[str, Any]] = []
    is_terminal: bool = False


class ProcessResultOut(BaseModel):
    meeting_id: str
    transcript_saved: bool
    analysis_saved: bool
    skipped_reason: str | None = None
    # True when Recall had no transcript and Groq Whisper produced the text.
    used_whisper_fallback: bool = False
    word_count: int | None = None
    participants: int | None = None
    action_items: int | None = None
    deadlines: int | None = None
    tokens_used: int | None = None
    commitments: dict[str, int] | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # Guard against silently switching which meeting the chat is about.
    confirm_context_switch: bool = False


class ChatResponse(BaseModel):
    meeting_id: str
    answer: str
    tokens_used: int | None = None
    context_switch_required: bool = False
    pending_meeting_id: str | None = None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    created_at: datetime
