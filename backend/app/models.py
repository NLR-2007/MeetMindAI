"""SQLAlchemy models for MeetMind AI.

Naming mirrors the domain: a user owns projects; a project holds meetings; a
meeting has participants, one transcript, one summary, and many action items
and deadlines.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# MySQL MEDIUMTEXT: transcripts outgrow the 64KB default TEXT column.
MEDIUM_TEXT = Text().with_variant(Text(16_777_215), "mysql")


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    # bcrypt hash; never the password itself.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # "employee" sees only their own work; "manager" also sees their reports'.
    role: Mapped[str] = mapped_column(String(16), default="employee", nullable=False)
    # Who this person reports to. Defines the manager's visibility scope.
    manager_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Names as they appear in transcripts, used to map commitments to people.
    display_names: Mapped[list[str] | None] = mapped_column(JSON)

    projects: Mapped[list[Project]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    meetings: Mapped[list[Meeting]] = relationship(back_populates="owner")


class Team(Base, TimestampMixin):
    """A group of people who attend the same meetings.

    A team exists for one reason: so a single bot can cover a meeting instead
    of every attendee sending their own. It is explicitly NOT a visibility
    grant - membership lets you read meetings the team recorded, and nothing
    else. Promises, coaching and progress stay personal.
    """

    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    memberships: Mapped[list[TeamMembership]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    invites: Mapped[list[TeamInvite]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    meetings: Mapped[list[Meeting]] = relationship(back_populates="team")


class TeamMembership(Base, TimestampMixin):
    """One person's place in one team."""

    __tablename__ = "team_memberships"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "owner" can invite and remove; "member" can do neither.
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    # Meetings recorded before this moment stay invisible: joining a team must
    # never hand over conversations the person was not part of.
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    team: Mapped[Team] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship()


class TeamInvite(Base, TimestampMixin):
    """A link that lets someone join a team.

    Expiring and revocable on purpose: an invite link is a credential, and one
    that works forever is a standing invitation to everyone it is forwarded to.
    """

    __tablename__ = "team_invites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The secret in the URL. Unique so a lookup cannot collide.
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    max_uses: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    team: Mapped[Team] = relationship(back_populates="invites")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    owner: Mapped[User | None] = relationship(back_populates="projects")
    meetings: Mapped[list[Meeting]] = relationship(back_populates="project")


class Meeting(Base, TimestampMixin):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Recall identifiers. bot_id is how incoming webhooks locate this row.
    bot_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    recording_id: Mapped[str | None] = mapped_column(String(64), index=True)

    meeting_url: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    bot_name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))

    status: Mapped[str | None] = mapped_column(String(64), index=True)
    status_changes: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=list)

    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)

    consent_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Who dispatched the bot. Still one person, even for a team meeting:
    # somebody pressed the button and consented to the recording.
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    # Set when the meeting belongs to a team: every member may then read it,
    # while promises and coaching stay scoped to each person individually.
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )

    owner: Mapped[User | None] = relationship(back_populates="meetings")
    team: Mapped[Team | None] = relationship(back_populates="meetings")
    project: Mapped[Project | None] = relationship(back_populates="meetings")
    participants: Mapped[list[Participant]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    transcript: Mapped[Transcript | None] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", uselist=False
    )
    summary: Mapped[Summary | None] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", uselist=False
    )
    action_items: Mapped[list[ActionItem]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    deadlines: Mapped[list[Deadline]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    chat_messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class Participant(Base, TimestampMixin):
    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id", "recall_participant_id", name="uq_participant_per_meeting"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Per-meeting participant id from Recall (an int in the transcript payload).
    recall_participant_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(255))
    # Often null: do not rely on this to match application users.
    email: Mapped[str | None] = mapped_column(String(255))
    is_host: Mapped[bool] = mapped_column(Boolean, default=False)
    platform: Mapped[str | None] = mapped_column(String(64))

    meeting: Mapped[Meeting] = relationship(back_populates="participants")


class Transcript(Base, TimestampMixin):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Which engine produced this: recallai_streaming | whisper_fallback
    source: Mapped[str] = mapped_column(String(64), default="recallai_streaming")
    language: Mapped[str | None] = mapped_column(String(16))
    # Flattened "Speaker: text" rendering, used for LLM prompts and chat context.
    plain_text: Mapped[str | None] = mapped_column(MEDIUM_TEXT)
    # Raw utterance array from Recall, kept for timestamps and diarisation.
    utterances: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    meeting: Mapped[Meeting] = relationship(back_populates="transcript")


class Summary(Base, TimestampMixin):
    __tablename__ = "summaries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    summary_text: Mapped[str | None] = mapped_column(Text)
    decisions: Mapped[list[str] | None] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String(128))
    tokens_used: Mapped[int | None] = mapped_column(Integer)

    meeting: Mapped[Meeting] = relationship(back_populates="summary")


class ActionItem(Base, TimestampMixin):
    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    owner_name: Mapped[str | None] = mapped_column(String(255))
    due_text: Mapped[str | None] = mapped_column(String(255))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    # Who held this before it changed hands in the meeting. With owner_name
    # set, someone took it over; with owner_name null, they gave it up and
    # nobody picked it up.
    reassigned_from: Mapped[str | None] = mapped_column(String(255))

    meeting: Mapped[Meeting] = relationship(back_populates="action_items")


class Deadline(Base, TimestampMixin):
    __tablename__ = "deadlines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    what: Mapped[str] = mapped_column(Text, nullable=False)
    when_text: Mapped[str | None] = mapped_column(String(255))
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Set once this deadline has been written to Google Calendar.
    google_event_id: Mapped[str | None] = mapped_column(String(255))
    google_event_link: Mapped[str | None] = mapped_column(String(512))
    google_calendar_id: Mapped[str | None] = mapped_column(String(255))

    meeting: Mapped[Meeting] = relationship(back_populates="deadlines")


class ChatMessage(Base, TimestampMixin):
    """Per-meeting chat history, scoped so chat never leaks across meetings."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="chat_messages")


class Calendar(Base, TimestampMixin):
    """A Google/Outlook calendar connected through Recall Calendar V2.

    The Google refresh token is exchanged for a Recall calendar and is NOT
    stored here; Recall holds it. We keep only Recall's calendar id.
    """

    __tablename__ = "calendars"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    recall_calendar_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), default="google_calendar")
    email: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(64))
    # Our own copy of the Google refresh token. Recall holds one too, but that
    # one is theirs to manage; writing events back is our concern, not theirs.
    google_refresh_token: Mapped[str | None] = mapped_column(String(512))
    # Dedicated "MeetMind AI" calendar that generated events are written to,
    # so the user's primary calendar stays untouched.
    meetmind_calendar_id: Mapped[str | None] = mapped_column(String(255))
    # Auto-send a bot to every event that has a meeting link.
    auto_record: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PrioritySender(Base, TimestampMixin):
    """An address or domain whose mail actually matters.

    Early-stage teams run on shared mailboxes drowning in newsletters, so the
    one message from a client gets lost. Rather than trying to classify every
    email, the user names who counts and everything else is ignored - a
    smaller, honest promise than "we will work out what is important".
    """

    __tablename__ = "priority_senders"
    __table_args__ = (
        UniqueConstraint("owner_id", "pattern", name="uq_priority_sender"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Either a full address ("ravi@acme.com") or a bare domain ("acme.com").
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))


class InboundEmail(Base, TimestampMixin):
    """A message from a priority sender, with what MeetMind made of it.

    The body is deliberately NOT stored: the summary and any extracted
    commitments are what the product needs, and keeping full mail content
    would make this a mail archive with all the obligations that implies.
    """

    __tablename__ = "inbound_emails"
    __table_args__ = (
        UniqueConstraint("owner_id", "gmail_id", name="uq_inbound_email"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gmail_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(64))
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(998))
    received_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    # Which priority rule matched, so the user can see why it was surfaced.
    matched_pattern: Mapped[str | None] = mapped_column(String(255))

    summary: Mapped[str | None] = mapped_column(Text)
    # Short bullet list of what actually matters in the message.
    highlights: Mapped[list[str] | None] = mapped_column(JSON)
    # True when the model judged it time-sensitive, with why in `urgency_reason`.
    urgent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    urgency_reason: Mapped[str | None] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    owner: Mapped[User] = relationship()


class Memory(Base, TimestampMixin):
    """Backing table for MemoryService.

    MySQL is TEMPORARY storage so Hindsight can be swapped in later behind the
    same save_memory()/recall_memory() interface. Hindsight is NOT integrated.
    """

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="meeting")
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    relevance: Mapped[float | None] = mapped_column(Float)


Index("ix_memories_scope_lookup", Memory.scope, Memory.scope_id)


class Commitment(Base, TimestampMixin):
    """A promise, decision or responsibility tracked across meetings.

    PromiseMirror's unit of work. Distinct from ActionItem, which is a raw
    per-meeting extraction: a Commitment persists across meetings, carries
    status, and records supersession so an original decision is never lost.
    """

    __tablename__ = "commitments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    # The meeting this commitment was first made in.
    source_meeting_id: Mapped[str | None] = mapped_column(
        ForeignKey("meetings.id", ondelete="SET NULL"), index=True
    )

    kind: Mapped[str] = mapped_column(String(24), default="promise")  # promise|decision|question
    text: Mapped[str] = mapped_column(Text, nullable=False)
    owner_name: Mapped[str | None] = mapped_column(String(255))
    # Who held this before it changed hands. owner_name set means it was
    # handed over; owner_name null means it was dropped and left unclaimed.
    reassigned_from: Mapped[str | None] = mapped_column(String(255))
    due_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    due_text: Mapped[str | None] = mapped_column(String(255))

    # pending | completed | cancelled | superseded
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    # Evidence: the transcript line this was drawn from.
    evidence: Mapped[str | None] = mapped_column(Text)

    # Supersession keeps the original intact rather than overwriting it.
    superseded_by_id: Mapped[str | None] = mapped_column(String(32), index=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # Changes start as "proposed" until a later meeting confirms them.
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # The real user this commitment belongs to, resolved from owner_name.
    # Only ever set to someone inside the same team: no cross-team mapping.
    assigned_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    source_meeting: Mapped[Meeting | None] = relationship()


class PrepPlan(Base, TimestampMixin):
    """A Mark Up preparation briefing for an upcoming meeting."""

    __tablename__ = "prep_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    # Set once the prepared-for meeting actually happens, enabling coaching.
    meeting_id: Mapped[str | None] = mapped_column(
        ForeignKey("meetings.id", ondelete="SET NULL"), index=True
    )

    mode: Mapped[str] = mapped_column(String(16), default="existing")  # existing|new
    title: Mapped[str | None] = mapped_column(String(512))
    # Free-form intake for a brand-new project.
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    briefing: Mapped[str | None] = mapped_column(MEDIUM_TEXT)
    talking_points: Mapped[list[str] | None] = mapped_column(JSON)
    questions_to_ask: Mapped[list[str] | None] = mapped_column(JSON)
    open_commitments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)


class PracticeSession(Base, TimestampMixin):
    """An AI practice conversation against a preparation plan."""

    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    prep_plan_id: Mapped[str] = mapped_column(
        ForeignKey("prep_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    persona: Mapped[str] = mapped_column(String(32), default="client")  # client|manager|teammate
    transcript: Mapped[list[dict[str, str]] | None] = mapped_column(JSON)
    feedback: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[list[str] | None] = mapped_column(JSON)
    improvements: Mapped[list[str] | None] = mapped_column(JSON)


class CoachingNote(Base, TimestampMixin):
    """Private per-user coaching feedback for one meeting.

    Never surfaced to anyone but its owner.
    """

    __tablename__ = "coaching_notes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prep_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("prep_plans.id", ondelete="SET NULL")
    )

    category: Mapped[str] = mapped_column(String(48), default="general")
    suggestion: Mapped[str] = mapped_column(Text, nullable=False)
    # What the user actually said, in their own words.
    said: Mapped[str | None] = mapped_column(Text)
    # A concrete rewrite: the sentence to use next time.
    better: Mapped[str | None] = mapped_column(Text)
    # Transcript excerpt backing the suggestion; feedback without it is opinion.
    evidence: Mapped[str | None] = mapped_column(Text)
    # Users may reject feedback they consider inaccurate.
    rejected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
