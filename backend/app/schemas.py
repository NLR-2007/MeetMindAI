"""Request/response models for the MeetMind AI API."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Supported meeting platforms and the URL shapes Recall accepts.
# One platform can be written several ways, so each name owns a list of
# shapes. The returned name is what Recall is told, so it must stay one of
# Recall's own platform identifiers no matter which spelling matched.
MEETING_URL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "google_meet": [
        # Plain meet.google.com/abc-defg-hij, plus the /lookup/ aliases
        # Calendar hands out, and any trailing query string.
        re.compile(
            r"^https://meet\.google\.com/(lookup/[a-z0-9_-]+|[a-z]{3}-[a-z]{4}-[a-z]{3})"
            r"(\?.*)?$",
            re.I,
        )
    ],
    "zoom": [
        # /j/, /w/ and /s/ are join links; /my/ is a personal room.
        re.compile(r"^https://([a-z0-9.-]+\.)?zoom\.(us|com)/(j|w|s)/\d+", re.I),
        re.compile(r"^https://([a-z0-9.-]+\.)?zoom\.(us|com)/my/[a-z0-9._-]+", re.I),
    ],
    "teams": [re.compile(r"^https://teams\.(microsoft|live)\.com/", re.I)],
    "webex": [re.compile(r"^https://([a-z0-9-]+\.)?webex\.com/", re.I)],
    "slack": [re.compile(r"^https://app\.slack\.com/huddle/", re.I)],
    "goto": [
        re.compile(r"^https://(www\.)?(gotomeet\.me|goto\.com|gotomeeting\.com)/", re.I)
    ],
}

# What to tell someone whose link did not match. Kept next to the patterns so
# the two cannot drift apart.
SUPPORTED_PLATFORMS = "Google Meet, Zoom, Microsoft Teams, Webex, Slack huddles or GoTo"


def detect_platform(url: str) -> str | None:
    for platform, patterns in MEETING_URL_PATTERNS.items():
        if any(pattern.match(url) for pattern in patterns):
            return platform
    return None


class JoinMeetingRequest(BaseModel):
    meeting_url: str = Field(
        description="Full meeting link, e.g. https://meet.google.com/abc-defg-hij"
    )
    bot_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=512)
    project_id: str | None = None
    # Record for a team: one bot covers everyone, instead of one each.
    team_id: str | None = None
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
                f"Unrecognised meeting URL. Expected a link from {SUPPORTED_PLATFORMS}, "
                "for example https://meet.google.com/abc-defg-hij"
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
    # Which project this meeting belongs to, so history groups by workstream.
    project_id: str | None = None
    project_name: str | None = None
    # Set when the meeting was recorded for a team rather than one person.
    team_id: str | None = None
    team_name: str | None = None


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


class RecalledMemory(BaseModel):
    """A memory that fed this answer, shown so the user can check the source."""

    content: str
    created_at: str | None = None


class ChatResponse(BaseModel):
    meeting_id: str
    answer: str
    tokens_used: int | None = None
    context_switch_required: bool = False
    pending_meeting_id: str | None = None
    # Which store answered, and what it returned. Reported from the live
    # wiring, so it says "mysql" whenever Hindsight is unreachable.
    memory_backend: str = "mysql"
    recalled_memories: list[RecalledMemory] = []


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    created_at: datetime
