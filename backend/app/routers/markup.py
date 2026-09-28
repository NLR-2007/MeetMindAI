"""Mark Up: preparation plans, practice mode, coaching and progress."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user
from app.models import (
    CoachingNote,
    Commitment,
    Meeting,
    PracticeSession,
    PrepPlan,
    Project,
    User,
)
from app.services import markup as markup_service
from app.services import promisemirror
from app.services.groq_client import GroqError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["markup"])


# --- schemas ---------------------------------------------------------------


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ExistingPlanRequest(BaseModel):
    project_id: str | None = None
    title: str | None = Field(default=None, max_length=512)


class NewProjectIntake(BaseModel):
    purpose: str = Field(min_length=1)
    project_description: str | None = None
    participants: str | None = None
    agenda: str | None = None
    my_responsibilities: str | None = None
    desired_outcomes: str | None = None
    project_id: str | None = None


class PrepPlanOut(BaseModel):
    id: str
    mode: str
    title: str | None
    project_id: str | None
    meeting_id: str | None
    briefing: str | None
    talking_points: list[str]
    questions_to_ask: list[str]
    open_commitments: list[dict[str, Any]]
    risks: list[str]
    role_guidance: str | None = None
    opening_script: str | None = None
    speaking_strategy: list[str] = Field(default_factory=list)
    past_improvements: list[str] = Field(default_factory=list)
    past_coaching_count: int = 0
    created_at: str


class PracticeStart(BaseModel):
    persona: str = Field(default="client", pattern="^(client|manager|teammate)$")


class PracticeMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class CoachRequest(BaseModel):
    prep_plan_id: str | None = None


class CoachChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class LiveAnswerRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class LiveAssistConfig(BaseModel):
    meeting_id: str | None = None
    enabled: bool
    # Normally Live Assist answers questions OTHER people ask you. With this
    # on it also answers your own, so a single person can rehearse or demo it.
    answer_own_questions: bool = False


def _plan_out(p: PrepPlan) -> PrepPlanOut:
    context = p.context or {}
    return PrepPlanOut(
        id=p.id,
        mode=p.mode,
        title=p.title,
        project_id=p.project_id,
        meeting_id=p.meeting_id,
        briefing=p.briefing,
        talking_points=p.talking_points or [],
        questions_to_ask=p.questions_to_ask or [],
        open_commitments=p.open_commitments or [],
        risks=(context.get("risks") or []),
        role_guidance=context.get("role_guidance"),
        opening_script=context.get("opening_script"),
        speaking_strategy=context.get("speaking_strategy") or [],
        past_improvements=context.get("past_improvements") or [],
        past_coaching_count=context.get("past_coaching_count") or 0,
        created_at=p.created_at.isoformat(),
    )


# --- projects --------------------------------------------------------------


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[ProjectOut]:
    rows = db.scalars(
        select(Project).where(Project.owner_id == user.id).order_by(Project.name)
    )
    return [ProjectOut.model_validate(p) for p in rows]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ProjectOut:
    project = Project(name=payload.name, description=payload.description, owner_id=user.id)
    db.add(project)
    db.flush()
    return ProjectOut.model_validate(project)


# --- Mark Up ---------------------------------------------------------------


@router.get("/markup/plans", response_model=list[PrepPlanOut])
def list_plans(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[PrepPlanOut]:
    rows = db.scalars(
        select(PrepPlan)
        .where(PrepPlan.owner_user_id == user.id)
        .order_by(PrepPlan.created_at.desc())
    )
    return [_plan_out(p) for p in rows]


@router.get("/markup/plans/{plan_id}", response_model=PrepPlanOut)
def get_plan(
    plan_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> PrepPlanOut:
    plan = db.get(PrepPlan, plan_id)
    if plan is None or plan.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown plan {plan_id}")
    return _plan_out(plan)


@router.post("/markup/prepare/existing", response_model=PrepPlanOut, status_code=201)
async def prepare_existing(
    payload: ExistingPlanRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> PrepPlanOut:
    """Briefing built from the user's own authorised meeting history."""
    if payload.project_id:
        project = db.get(Project, payload.project_id)
        if project is None or project.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown project")

    if not settings.groq_api_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured.")

    try:
        plan = await markup_service.build_existing_project_plan(
            db,
            settings,
            owner_user_id=user.id,
            project_id=payload.project_id,
            title=payload.title,
        )
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc.detail}") from exc
    return _plan_out(plan)


@router.post("/markup/prepare/new", response_model=PrepPlanOut, status_code=201)
async def prepare_new(
    payload: NewProjectIntake,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> PrepPlanOut:
    if not settings.groq_api_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured.")
    intake = payload.model_dump(exclude={"project_id"})
    try:
        plan = await markup_service.build_new_project_plan(
            db,
            settings,
            owner_user_id=user.id,
            project_id=payload.project_id,
            intake=intake,
        )
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc.detail}") from exc
    return _plan_out(plan)


# --- practice mode ---------------------------------------------------------


@router.post("/markup/plans/{plan_id}/practice", status_code=201)
async def start_practice(
    plan_id: str,
    payload: PracticeStart,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    plan = db.get(PrepPlan, plan_id)
    if plan is None or plan.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown plan {plan_id}")

    topic = plan.title or "the upcoming meeting"
    try:
        opening = await markup_service.practice_turn(
            settings, persona=payload.persona, topic=topic, history=[], user_message=None
        )
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc.detail}") from exc

    session = PracticeSession(
        prep_plan_id=plan.id,
        owner_user_id=user.id,
        persona=payload.persona,
        transcript=[{"role": "assistant", "content": opening}],
    )
    db.add(session)
    db.flush()
    return {"session_id": session.id, "persona": session.persona, "opening": opening}


@router.post("/markup/practice/{session_id}/reply")
async def practice_reply(
    session_id: str,
    payload: PracticeMessage,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    session = db.get(PracticeSession, session_id)
    if session is None or session.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown session {session_id}")

    plan = db.get(PrepPlan, session.prep_plan_id)
    history = list(session.transcript or [])
    try:
        reply = await markup_service.practice_turn(
            settings,
            persona=session.persona,
            topic=(plan.title if plan else None) or "the meeting",
            history=history,
            user_message=payload.message,
        )
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc.detail}") from exc

    history.append({"role": "user", "content": payload.message})
    history.append({"role": "assistant", "content": reply})
    session.transcript = history
    db.flush()
    return {"session_id": session.id, "reply": reply, "turns": len(history)}


@router.post("/markup/practice/{session_id}/finish")
async def finish_practice(
    session_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    session = db.get(PracticeSession, session_id)
    if session is None or session.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown session {session_id}")
    if not session.transcript:
        raise HTTPException(status_code=409, detail="Nothing was practised yet.")

    try:
        result = await markup_service.practice_feedback(
            settings, transcript=session.transcript
        )
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc.detail}") from exc

    session.feedback = result["feedback"]
    session.strengths = result["strengths"]
    session.improvements = result["improvements"]
    db.flush()
    return {"session_id": session.id, **result}


def _live_answer_context(db: Session, plan: PrepPlan) -> str:
    practice = db.scalar(
        select(PracticeSession)
        .where(PracticeSession.prep_plan_id == plan.id)
        .order_by(PracticeSession.created_at.desc())
        .limit(1)
    )
    public_context = {
        key: value
        for key, value in (plan.context or {}).items()
        if not key.startswith("_live_assist")
    }
    parts = [
        f"Meeting: {plan.title or 'Upcoming meeting'}",
        f"Briefing: {plan.briefing or ''}",
        f"Intake: {json.dumps(public_context, ensure_ascii=False)}",
        "Talking points: " + "; ".join(plan.talking_points or []),
        "Questions prepared: " + "; ".join(plan.questions_to_ask or []),
        "Open commitments: " + json.dumps(plan.open_commitments or [], ensure_ascii=False),
    ]
    if practice and practice.transcript:
        parts.append(
            "Most recent practice:\n"
            + "\n".join(
                f"{turn.get('role', 'unknown')}: {turn.get('content', '')}"
                for turn in practice.transcript[-12:]
            )
        )
    return "\n".join(parts)


# How long the speaker must pause before we treat a question as finished.
SILENCE_SECONDS = 2.5
# Longer when there is no question mark: the sentence may still be in progress.
SILENCE_SECONDS_UNPUNCTUATED = 4.0
# Consecutive chunks from one speaker closer than this are one utterance.
SPEECH_JOIN_SECONDS = 3.0


def _seconds_between(earlier: Any, later: Any) -> float | None:
    """Gap between two ISO timestamps, or None if either is unusable."""
    try:
        a = datetime.fromisoformat(str(earlier).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(later).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return abs((b - a).total_seconds())


def _addressed_to(text: str, own_names: set[str]) -> str:
    """Work out whether a question was aimed at this user.

    Returns "you" when they are named, "someone_else" when a different person
    is clearly named, and "room" when nobody is. Only names actually spoken
    count: an unaddressed question is open to anyone, so it stays "room".
    """
    # Strip punctuation so "Bunny," and "Bunny?" still match the name "bunny".
    words = re.findall(r"[a-z0-9']+", text.lower())
    padded = " " + " ".join(words) + " "

    for name in own_names:
        name = (name or "").strip().lower()
        if len(name) >= 3 and f" {name} " in padded:
            return "you"

    # A vocative sits at one end: "Priya, can you…" or "…, Priya?"
    segments = [seg.strip() for seg in text.lower().rstrip("?. ").split(",")]
    if len(segments) > 1:
        for candidate in (segments[0], segments[-1]):
            parts = re.findall(r"[a-z']+", candidate)
            if not 1 <= len(parts) <= 2:
                continue
            # "when will you…" is a question opener, not a name.
            if _looks_like_question(candidate):
                continue
            if parts[0] in {"so", "ok", "okay", "right", "well", "and", "but", "yes", "no"}:
                continue
            return "someone_else"
    return "room"


def _looks_like_question(text: str) -> bool:
    value = text.strip().lower()
    starters = (
        "what ", "why ", "how ", "when ", "where ", "who ", "which ",
        "can ", "could ", "would ", "will ", "do ", "does ", "did ",
        "is ", "are ", "should ", "have ", "has ", "tell me ", "explain ",
    )
    return value.endswith("?") or value.startswith(starters)


@router.post("/markup/plans/{plan_id}/live-answer")
async def live_answer(
    plan_id: str,
    payload: LiveAnswerRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Return a private, speakable answer grounded in preparation and practice."""
    plan = db.get(PrepPlan, plan_id)
    if plan is None or plan.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown plan {plan_id}")
    if not settings.groq_api_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured.")
    try:
        answer = await markup_service.suggest_live_answer(
            settings,
            question=payload.question.strip(),
            context=_live_answer_context(db, plan),
        )
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc.detail}") from exc
    return {"answer": answer}


@router.post("/markup/plans/{plan_id}/live-assist")
def configure_live_assist(
    plan_id: str,
    payload: LiveAssistConfig,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    plan = db.get(PrepPlan, plan_id)
    if plan is None or plan.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown plan {plan_id}")
    if payload.enabled:
        meeting = db.get(Meeting, payload.meeting_id)
        if meeting is None or meeting.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Choose one of your meetings")
        plan.meeting_id = meeting.id
    context = dict(plan.context or {})
    context["_live_assist_enabled"] = payload.enabled
    context["_live_assist_answer_own"] = payload.answer_own_questions
    if not payload.enabled:
        context.pop("_live_assist_question", None)
        context.pop("_live_assist_answer", None)
    plan.context = context
    db.flush()
    return {
        "enabled": payload.enabled,
        "meeting_id": plan.meeting_id,
        "answer_own_questions": payload.answer_own_questions,
    }


@router.get("/markup/plans/{plan_id}/live-assist")
async def live_assist_status(
    plan_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    plan = db.get(PrepPlan, plan_id)
    if plan is None or plan.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown plan {plan_id}")
    context = dict(plan.context or {})
    if not context.get("_live_assist_enabled") or not plan.meeting_id:
        return {"enabled": False, "state": "off", "question": None, "answer": None}
    answering_own = bool(context.get("_live_assist_answer_own"))

    meeting = db.get(Meeting, plan.meeting_id)
    if meeting is None or meeting.owner_id != user.id:
        return {"enabled": False, "state": "off", "question": None, "answer": None}
    utterances = [
        item for item in ((meeting.transcript.utterances if meeting.transcript else None) or [])
        if item.get("received_at") and item.get("text")
    ]
    if not utterances:
        return {"enabled": True, "state": "listening", "question": None, "answer": None}

    # Recall streams speech in chunks, so one spoken question can arrive as
    # several utterances. Stitch together the trailing run from one speaker
    # before deciding anything, or we answer half a sentence.
    latest = utterances[-1]
    latest_speaker = str(latest.get("participant_id") or "")
    run = [latest]
    for item in reversed(utterances[:-1]):
        if str(item.get("participant_id") or "") != latest_speaker:
            break
        gap = _seconds_between(item.get("received_at"), run[0].get("received_at"))
        if gap is None or gap > SPEECH_JOIN_SECONDS:
            break
        run.insert(0, item)

    question = " ".join(str(i.get("text") or "").strip() for i in run).strip()
    speaker_email = str(latest.get("participant_email") or "").strip().lower()
    speaker_name = str(latest.get("participant_name") or "").strip().lower()
    own_names = {
        str(user.name or "").strip().lower(),
        *(str(name).strip().lower() for name in (user.display_names or [])),
    }
    spoken_by_me = speaker_email == user.email.lower() or (
        speaker_name and speaker_name in own_names
    )
    answer_own = bool(context.get("_live_assist_answer_own"))
    if (spoken_by_me and not answer_own) or not _looks_like_question(question):
        return {"enabled": True, "state": "listening", "question": None, "answer": None}

    # A question aimed at someone else by name is not yours to answer.
    audience = _addressed_to(question, {n for n in own_names if n})
    if audience == "someone_else" and not answer_own:
        return {
            "enabled": True,
            "state": "listening",
            "question": None,
            "answer": None,
            "skipped": "addressed to someone else",
        }

    received_at = datetime.fromisoformat(str(latest["received_at"]).replace("Z", "+00:00"))
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    # A question that does not end with "?" is probably still being spoken, so
    # give it longer before assuming the speaker has finished.
    finished = question.rstrip().endswith("?")
    silence_needed = SILENCE_SECONDS if finished else SILENCE_SECONDS_UNPUNCTUATED
    quiet_for = (datetime.now(timezone.utc) - received_at).total_seconds()
    if quiet_for < silence_needed:
        return {"enabled": True, "state": "waiting", "question": question, "answer": None}

    question_key = f"{latest.get('participant_id', '')}:{latest.get('end', '')}:{question}"
    if context.get("_live_assist_question") == question_key and context.get("_live_assist_answer"):
        return {
            "enabled": True,
            "state": "ready",
            "question": question,
            "answer": context["_live_assist_answer"],
            "addressed_to": audience,
        }
    if not settings.groq_api_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured.")
    try:
        answer = await markup_service.suggest_live_answer(
            settings,
            question=question,
            context=_live_answer_context(db, plan),
        )
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc.detail}") from exc
    context["_live_assist_question"] = question_key
    context["_live_assist_answer"] = answer
    plan.context = context
    db.flush()
    return {
        "enabled": True,
        "state": "ready",
        "question": question,
        "answer": answer,
        "addressed_to": audience,
    }


# --- personal coaching -----------------------------------------------------


@router.post("/coach/{meeting_id}/review", status_code=201)
async def review_meeting(
    meeting_id: str,
    payload: CoachRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Compare preparation against what was actually said. Private to the user."""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or meeting.owner_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown meeting_id {meeting_id}")

    plan = None
    if payload.prep_plan_id:
        plan = db.get(PrepPlan, payload.prep_plan_id)
        if plan is None or plan.owner_user_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown plan")
    else:
        plan = db.scalar(
            select(PrepPlan)
            .where(PrepPlan.owner_user_id == user.id, PrepPlan.meeting_id == meeting.id)
            .order_by(PrepPlan.created_at.desc())
        )

    if not settings.groq_api_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured.")

    try:
        suggestions = await markup_service.coach_on_meeting(
            db, settings, meeting=meeting, plan=plan, user=user
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc.detail}") from exc

    # Replace previous notes for this meeting rather than stacking duplicates.
    for old in db.scalars(
        select(CoachingNote).where(
            CoachingNote.owner_user_id == user.id, CoachingNote.meeting_id == meeting.id
        )
    ):
        db.delete(old)
    db.flush()

    created = []
    for s in suggestions:
        note = CoachingNote(
            owner_user_id=user.id,
            meeting_id=meeting.id,
            prep_plan_id=plan.id if plan else None,
            category=s["category"],
            suggestion=s["suggestion"],
            said=s.get("said"),
            better=s.get("better"),
            evidence=s["evidence"],
        )
        db.add(note)
        created.append(note)
    db.flush()

    return {
        "meeting_id": meeting.id,
        "had_plan": plan is not None,
        "count": len(created),
        "notes": [
            {
                "id": n.id,
                "category": n.category,
                "said": n.said,
                "suggestion": n.suggestion,
                "better": n.better,
                "evidence": n.evidence,
            }
            for n in created
        ],
    }


@router.get("/coach/notes")
def list_notes(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, Any]:
    """This user's coaching history, plus recurring themes."""
    rows = list(
        db.scalars(
            select(CoachingNote)
            .where(CoachingNote.owner_user_id == user.id)
            .order_by(CoachingNote.created_at.desc())
        )
    )
    themes: dict[str, int] = {}
    for n in rows:
        if not n.rejected:
            themes[n.category] = themes.get(n.category, 0) + 1

    meetings = {m.id: m for m in db.scalars(select(Meeting).where(Meeting.owner_id == user.id))}
    return {
        "recurring_themes": sorted(themes.items(), key=lambda kv: -kv[1]),
        "notes": [
            {
                "id": n.id,
                "meeting_id": n.meeting_id,
                "meeting_title": (
                    meetings[n.meeting_id].title or meetings[n.meeting_id].meeting_url
                )
                if n.meeting_id in meetings
                else None,
                "category": n.category,
                "said": n.said,
                "suggestion": n.suggestion,
                "better": n.better,
                "evidence": n.evidence,
                "rejected": n.rejected,
                "created_at": n.created_at.isoformat(),
            }
            for n in rows
        ],
    }


@router.post("/coach/{meeting_id}/ask")
async def ask_personal_coach(
    meeting_id: str,
    payload: CoachChatRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Private follow-up coaching grounded in one reviewed meeting."""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or meeting.owner_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown meeting_id {meeting_id}")
    if meeting.transcript is None and meeting.summary is None:
        raise HTTPException(status_code=409, detail="This meeting has no transcript or summary yet.")
    if not settings.groq_api_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured.")

    meeting_notes = list(
        db.scalars(
            select(CoachingNote)
            .where(
                CoachingNote.owner_user_id == user.id,
                CoachingNote.meeting_id == meeting.id,
                CoachingNote.rejected.is_(False),
            )
            .order_by(CoachingNote.created_at.desc())
        )
    )
    recent_notes = list(
        db.scalars(
            select(CoachingNote)
            .where(
                CoachingNote.owner_user_id == user.id,
                CoachingNote.rejected.is_(False),
            )
            .order_by(CoachingNote.created_at.desc())
            .limit(12)
        )
    )
    context_parts = [f"Reviewed meeting: {meeting.title or meeting.meeting_url}"]
    if meeting.summary:
        context_parts.append(f"Summary: {meeting.summary.summary_text or ''}")
        context_parts.extend(f"Decision: {decision}" for decision in (meeting.summary.decisions or []))
    if meeting.transcript and meeting.transcript.plain_text:
        context_parts.append(f"Transcript:\n{meeting.transcript.plain_text}")
    if meeting_notes:
        context_parts.append("Coaching feedback for this meeting:")
        context_parts.extend(f"- {note.category}: {note.suggestion} (evidence: {note.evidence or 'none'})" for note in meeting_notes)
    if recent_notes:
        context_parts.append("Recurring private coaching themes:")
        context_parts.extend(f"- {note.category}: {note.suggestion}" for note in recent_notes)

    try:
        answer = await markup_service.answer_coaching_question(
            settings,
            question=payload.message,
            context="\n".join(context_parts),
            history=payload.history,
        )
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {exc.detail}") from exc
    return {"answer": answer}


@router.post("/coach/notes/{note_id}/reject")
def reject_note(
    note_id: str,
    rejected: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Users decide what feedback is fair; rejected notes stop counting."""
    note = db.get(CoachingNote, note_id)
    if note is None or note.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Unknown note {note_id}")
    note.rejected = rejected
    db.flush()
    return {"id": note.id, "rejected": note.rejected}


# --- progress dashboard ----------------------------------------------------


@router.get("/progress")
def progress(
    project_id: str | None = None,
    assigned_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Progress for the caller.

    An employee sees only their own commitments. A manager sees the whole team
    and can narrow to one person with `assigned_to`.
    """
    from app.services import team as team_service

    now = datetime.now(timezone.utc)
    # Personal dashboard: own work only. The team has its own section.
    visible = [user.id]

    stmt = select(Commitment).where(team_service.own_commitments_filter(user))
    if assigned_to:
        if assigned_to not in visible:
            raise HTTPException(status_code=404, detail="Unknown team member")
        stmt = stmt.where(Commitment.assigned_user_id == assigned_to)
    if project_id:
        stmt = stmt.where(Commitment.project_id == project_id)
    commitments = list(db.scalars(stmt))

    def _due(c: Commitment) -> datetime | None:
        if c.due_at is None:
            return None
        return c.due_at if c.due_at.tzinfo else c.due_at.replace(tzinfo=timezone.utc)

    pending = [c for c in commitments if c.status == "pending"]
    completed = [c for c in commitments if c.status == "completed"]
    overdue = [c for c in pending if (d := _due(c)) and d < now]
    upcoming = [
        c for c in pending if (d := _due(c)) and now <= d <= now + timedelta(days=14)
    ]

    # Per-project rollup.
    projects = {p.id: p for p in db.scalars(select(Project).where(Project.owner_id.in_(visible)))}
    by_project: dict[str, dict[str, Any]] = {}
    for c in commitments:
        key = c.project_id or "unassigned"
        row = by_project.setdefault(
            key,
            {
                "project_id": c.project_id,
                "project_name": projects[key].name if key in projects else "Unassigned",
                "total": 0,
                "completed": 0,
                "pending": 0,
                "overdue": 0,
            },
        )
        row["total"] += 1
        if c.status == "completed":
            row["completed"] += 1
        elif c.status == "pending":
            row["pending"] += 1
            d = _due(c)
            if d and d < now:
                row["overdue"] += 1
    for row in by_project.values():
        row["percent"] = round(100 * row["completed"] / row["total"]) if row["total"] else 0

    meeting_stmt = select(Meeting).where(Meeting.owner_id.in_(visible))
    if project_id:
        meeting_stmt = meeting_stmt.where(Meeting.project_id == project_id)
    recent = list(db.scalars(meeting_stmt.order_by(Meeting.created_at.desc()).limit(5)))

    findings = promisemirror.analyse(
        db,
        owner_user_id=user.id,
        project_id=project_id,
        assigned_to=assigned_to,
        visible_user_ids=visible,
    )

    def _c(c: Commitment) -> dict[str, Any]:
        d = _due(c)
        return {
            "id": c.id,
            "text": c.text,
            "owner_name": c.owner_name,
            "status": c.status,
            "due_at": d.isoformat() if d else None,
            "project_id": c.project_id,
            "meeting_id": c.source_meeting_id,
        }

    return {
        "totals": {
            "pending": len(pending),
            "completed": len(completed),
            "overdue": len(overdue),
            "upcoming": len(upcoming),
        },
        "pending": [_c(c) for c in pending],
        "completed": [_c(c) for c in completed],
        "overdue": [_c(c) for c in overdue],
        "upcoming": [_c(c) for c in upcoming],
        "by_project": list(by_project.values()),
        "recent_meetings": [
            {
                "id": m.id,
                "title": m.title or m.meeting_url,
                "status": m.status,
                "created_at": m.created_at.isoformat(),
            }
            for m in recent
        ],
        "alerts": [f.as_dict() for f in findings if f.severity in {"high", "medium"}][:10],
    }
