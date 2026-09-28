"""Mark Up (meeting preparation), AI practice, and personal coaching.

All three share one idea: compare what a user *intended* with what a user
*actually did*, using only evidence that exists in their own records.

Coaching output is deliberately constrained. The prompt forbids inventing
mistakes, every suggestion must quote a transcript line, and the user can
reject any suggestion they consider wrong.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import CoachingNote, Commitment, Meeting, PrepPlan, Project
from app.services.groq_client import GroqClient, GroqError
from app.services.memory import get_memory_service
from app.services.promisemirror import analyse as analyse_commitments

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = """You prepare a person for an upcoming meeting.

Return ONLY valid JSON:
{
  "briefing": string,
  "talking_points": [string],
  "questions_to_ask": [string],
  "risks": [string]
}

Rules:
- Use ONLY the context provided. Never invent history, names, or decisions.
- "briefing" is short prose the person can read in under a minute.
- "questions_to_ask" are things the context suggests are unresolved, especially
  questions they appear not to have asked yet.
- If the context is thin, say so plainly in the briefing rather than padding.
"""

NEW_PROJECT_PROMPT = """You prepare a person for a first meeting on a new project.

Return ONLY valid JSON:
{
  "briefing": string,
  "role_guidance": string,
  "opening_script": string,
  "speaking_strategy": [string],
  "past_improvements": [string],
  "talking_points": [string],
  "questions_to_ask": [string],
  "risks": [string]
}

Base everything on the intake the person gave you. Do not invent stakeholders,
budgets, or constraints they did not mention.
- Explain the person's role and the value they should bring to this meeting.
- Give practical guidance on how to speak, structure points, and handle questions.
- Write an opening script they can adapt, not a claim they must repeat verbatim.
- When PRIVATE PAST COACHING is provided, turn it into specific improvements for
  this meeting. Do not repeat transcript quotes or expose private history.
- If no past coaching exists, say so through an empty past_improvements list.
- Fit every suggestion to the stated audience, responsibilities, and outcome.
"""

PRACTICE_PROMPT = """You are role-playing a meeting counterpart so someone can practise.

You are acting as: {persona}.
The meeting is about: {topic}

Behave like a real {persona}: ask one focused question at a time, follow up on
vague answers, and stay in character. Do not coach or break character during
the conversation. Keep each turn under 60 words.
"""

FEEDBACK_PROMPT = """You review a practice conversation and give honest, usable feedback.

Return ONLY valid JSON:
{
  "feedback": string,
  "strengths": [string],
  "improvements": [string]
}

Rules:
- Base every point on what was actually said in the practice transcript.
- Do not invent weaknesses. If they did well, say so.
- "improvements" are concrete and actionable, not vague advice.
- At most 5 improvements.
"""

COACHING_PROMPT = """You coach ONE person on how they spoke in a meeting.

You are given the full transcript for context, and separately the lines that
THIS PERSON said. Other people's lines are context only.

Return ONLY valid JSON:
{
  "suggestions": [
    {
      "category": string,
      "said": string,
      "issue": string,
      "better": string,
      "evidence": string
    }
  ]
}

Field meanings:
- "said": what this person actually said, in their own words, briefly.
- "issue": what was unclear, missing or repeated about it. One sentence.
- "better": a concrete rewrite — the sentence they could say next time.
  Write it as words they could speak, not advice about speaking.
- "evidence": a short quote copied VERBATIM from THIS PERSON'S LINES only.

Rules:
- Between 3 and 5 suggestions.
- Every point must be about something THIS PERSON said or failed to say.
  Never criticise them for another speaker's words, questions or omissions.
- "evidence" must appear verbatim in THIS PERSON'S LINES. If you cannot quote
  them, do not make that point.
- Never invent mistakes. Never speculate about intent, tone or feelings.
- Speech-to-text errors are not the speaker's mistakes; ignore them.
- Categories: missed_point, unanswered_question, unclear_commitment,
  repetition, clarity.
- If they did well, return fewer suggestions rather than manufacturing
  criticism.
"""

COACH_CHAT_PROMPT = """You are a private, practical meeting communication coach.

Help the user understand their coaching feedback and prepare how to speak in
their next meeting.
- Ground claims about the reviewed meeting in the supplied meeting record.
- Clearly distinguish transcript-backed observations from forward-looking advice.
- Never invent a weakness, decision, stakeholder, or fact.
- Give concise, usable wording examples when the user asks what to say.
- Use prior coaching themes only to help this user improve; do not expose or
  discuss privacy implementation details.
- Prefer specific suggestions, short rehearsal scripts, and clear next steps.
- Format for a narrow chat panel: start with the direct answer, keep paragraphs
  short, and use concise Markdown headings and bullets where helpful.
- Avoid Markdown tables, raw HTML, and long report-style introductions.
- Use no more than three sections unless the user explicitly asks for a
  detailed review. End with one practical next step or rehearsal prompt.
"""

LIVE_ANSWER_PROMPT = """You privately help a person answer a question during a live meeting.

Use only the supplied preparation plan and practice history.
- Return a short, natural first-person answer the person can say aloud now.
- Keep it under 80 words and lead with the direct answer.
- Do not mention AI, the preparation plan, or practice history.
- Never invent a number, date, decision, capability, or project fact.
- If the context is insufficient, say what is unknown and provide one safe
  clarifying response the person can use instead.
- Use plain text, not headings, tables, or a long explanation.
"""


async def _ask_json(client: GroqClient, system: str, user: str) -> dict[str, Any]:
    content, _tokens = await client._chat(  # noqa: SLF001
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        json_mode=True,
    )
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise GroqError(200, f"Model returned invalid JSON: {content[:200]}") from exc


def gather_project_context(
    db: Session, *, owner_user_id: str, project_id: str | None, limit_meetings: int = 6
) -> dict[str, Any]:
    """Everything the user is authorised to see about this project."""
    stmt = select(Meeting).where(Meeting.owner_id == owner_user_id)
    if project_id:
        stmt = stmt.where(Meeting.project_id == project_id)
    meetings = list(
        db.scalars(stmt.order_by(Meeting.created_at.desc()).limit(limit_meetings))
    )

    history: list[dict[str, Any]] = []
    for m in meetings:
        history.append(
            {
                "meeting_id": m.id,
                "title": m.title or m.meeting_url,
                "when": m.created_at.isoformat(),
                "summary": m.summary.summary_text if m.summary else None,
                "decisions": (m.summary.decisions if m.summary else []) or [],
                "action_items": [
                    {"task": a.task, "owner": a.owner_name, "due": a.due_text}
                    for a in m.action_items
                ],
                "participants": [p.name for p in m.participants if p.name],
            }
        )

    findings = analyse_commitments(db, owner_user_id=owner_user_id, project_id=project_id)
    open_commitments = [
        f.as_dict()
        for f in findings
        if f.kind in {"overdue", "approaching", "undated", "unowned", "changed"}
    ]

    return {"meetings": history, "open_commitments": open_commitments}


def _context_text(context: dict[str, Any]) -> str:
    parts: list[str] = []
    for m in context["meetings"]:
        parts.append(f"--- Meeting: {m['title']} ({m['when'][:10]}) ---")
        if m["summary"]:
            parts.append(f"Summary: {m['summary']}")
        for d in m["decisions"]:
            parts.append(f"Decision: {d}")
        for a in m["action_items"]:
            parts.append(
                f"Action: {a['task']} (owner: {a['owner'] or 'unassigned'}, due: {a['due'] or 'n/a'})"
            )
    if context["open_commitments"]:
        parts.append("\n--- Unresolved commitments ---")
        for c in context["open_commitments"]:
            parts.append(f"[{c['kind']}] {c['title']} — {c['detail']}")
    return "\n".join(parts) if parts else "(no prior meetings on record)"


async def build_existing_project_plan(
    db: Session,
    settings: Settings,
    *,
    owner_user_id: str,
    project_id: str | None,
    title: str | None,
) -> PrepPlan:
    context = gather_project_context(db, owner_user_id=owner_user_id, project_id=project_id)

    prompt = _context_text(context)
    # Hindsight adds anything semantically relevant that the recent-meeting
    # window missed.
    memory = get_memory_service(db)
    if project_id:
        recalled = memory.recall_memory(
            title or "upcoming meeting", scope="project", scope_id=project_id, limit=8
        )
        if recalled:
            prompt += "\n\n--- Recalled from project memory ---\n" + "\n".join(
                f"- {r['content']}" for r in recalled
            )

    client = GroqClient(settings)
    data = await _ask_json(
        client,
        BRIEFING_PROMPT,
        f"Upcoming meeting: {title or 'untitled'}\n\nContext:\n{prompt}",
    )

    plan = PrepPlan(
        owner_user_id=owner_user_id,
        project_id=project_id,
        mode="existing",
        title=title,
        briefing=data.get("briefing"),
        talking_points=data.get("talking_points") or [],
        questions_to_ask=data.get("questions_to_ask") or [],
        open_commitments=context["open_commitments"],
        context={"risks": data.get("risks") or []},
    )
    db.add(plan)
    db.flush()
    return plan


async def build_new_project_plan(
    db: Session,
    settings: Settings,
    *,
    owner_user_id: str,
    project_id: str | None,
    intake: dict[str, Any],
) -> PrepPlan:
    lines = [f"{k.replace('_', ' ').title()}: {v}" for k, v in intake.items() if v]
    past_notes = list(
        db.scalars(
            select(CoachingNote)
            .where(
                CoachingNote.owner_user_id == owner_user_id,
                CoachingNote.rejected.is_(False),
            )
            .order_by(CoachingNote.created_at.desc())
            .limit(12)
        )
    )
    if past_notes:
        lines.append("\nPRIVATE PAST COACHING (use only to improve this user's preparation):")
        lines.extend(
            f"- {note.category}: {note.suggestion}" for note in past_notes
        )
    client = GroqClient(settings)
    data = await _ask_json(client, NEW_PROJECT_PROMPT, "\n".join(lines))

    plan = PrepPlan(
        owner_user_id=owner_user_id,
        project_id=project_id,
        mode="new",
        title=intake.get("purpose") or "New project meeting",
        briefing=data.get("briefing"),
        talking_points=data.get("talking_points") or [],
        questions_to_ask=data.get("questions_to_ask") or [],
        open_commitments=[],
        context={
            "intake": intake,
            "risks": data.get("risks") or [],
            "role_guidance": data.get("role_guidance"),
            "opening_script": data.get("opening_script"),
            "speaking_strategy": data.get("speaking_strategy") or [],
            "past_improvements": data.get("past_improvements") or [],
            "past_coaching_count": len(past_notes),
        },
    )
    db.add(plan)
    db.flush()
    return plan


async def practice_turn(
    settings: Settings,
    *,
    persona: str,
    topic: str,
    history: list[dict[str, str]],
    user_message: str | None,
) -> str:
    """One turn of the simulated meeting."""
    client = GroqClient(settings)
    messages = [
        {"role": "system", "content": PRACTICE_PROMPT.format(persona=persona, topic=topic)}
    ]
    messages.extend(history)
    messages.append(
        {
            "role": "user",
            "content": user_message
            or "Start the meeting with your first question.",
        }
    )
    reply, _ = await client._chat(messages, temperature=0.6)  # noqa: SLF001
    return reply


async def practice_feedback(
    settings: Settings, *, transcript: list[dict[str, str]]
) -> dict[str, Any]:
    convo = "\n".join(f"{t['role']}: {t['content']}" for t in transcript)
    data = await _ask_json(GroqClient(settings), FEEDBACK_PROMPT, convo)
    return {
        "feedback": data.get("feedback") or "",
        "strengths": data.get("strengths") or [],
        "improvements": (data.get("improvements") or [])[:5],
    }


def split_transcript_by_speaker(
    transcript_text: str, aliases: list[str]
) -> tuple[list[str], list[str]]:
    """Separate one person's lines from everyone else's.

    Transcript lines are "Speaker: words". Matching is on the speaker prefix
    only, so a person is never credited with a line merely because their name
    was mentioned in it.
    """
    mine: list[str] = []
    others: list[str] = []
    needles = [a.strip().lower() for a in aliases if a and len(a.strip()) >= 3]

    for line in (transcript_text or "").splitlines():
        if not line.strip():
            continue
        speaker, _, said = line.partition(":")
        if not said:
            others.append(line)
            continue
        who = speaker.strip().lower()
        if any(n == who or n in who or who in n for n in needles):
            mine.append(line.strip())
        else:
            others.append(line.strip())
    return mine, others


async def coach_on_meeting(
    db: Session,
    settings: Settings,
    *,
    meeting: Meeting,
    plan: PrepPlan | None,
    user: User,
) -> list[dict[str, Any]]:
    """Coach ONE user on their own contribution to a meeting.

    In a meeting with ten people, each person must be reviewed only on what
    they themselves said. The transcript is split by speaker first; if this
    user cannot be found in it, we refuse rather than review someone else's
    words as if they were theirs.
    """
    if meeting.transcript is None or not meeting.transcript.plain_text:
        raise ValueError("This meeting has no transcript to review.")

    aliases = list(user.display_names or [])
    if user.name:
        aliases.append(user.name)
        aliases.extend(user.name.split())
    if user.email:
        aliases.append(user.email.split("@")[0])

    mine, others = split_transcript_by_speaker(
        meeting.transcript.plain_text, aliases
    )

    if not mine:
        speakers = sorted(
            {line.split(":", 1)[0].strip() for line in others if ":" in line}
        )
        raise ValueError(
            "Could not find you in this transcript, so there is nothing of "
            "yours to review. Speakers recorded were: "
            + (", ".join(speakers) or "none")
            + ". Add the name you are called in meetings under your profile "
            "aliases and try again."
        )

    planned = "(no preparation plan was made for this meeting)"
    if plan:
        planned = "\n".join(
            [
                f"Briefing: {plan.briefing or ''}",
                "Planned talking points:",
                *[f"- {t}" for t in (plan.talking_points or [])],
                "Questions they meant to ask:",
                *[f"- {q}" for q in (plan.questions_to_ask or [])],
            ]
        )

    speaker_label = user.name or user.email
    user_prompt = (
        f"PLANNED:\n{planned}\n\n"
        f"THIS PERSON'S LINES ({speaker_label}):\n"
        + "\n".join(mine)
        + "\n\nOTHER SPEAKERS (context only, never criticise them for these):\n"
        + "\n".join(others[:200])
    )
    data = await _ask_json(GroqClient(settings), COACHING_PROMPT, user_prompt)

    # The quote must come from this user's own words. Checking against the
    # whole transcript would let another speaker's line through.
    own_text = "\n".join(mine).lower()
    out: list[dict[str, Any]] = []
    for item in data.get("suggestions", [])[:5]:
        evidence = (item.get("evidence") or "").strip()
        if evidence and evidence.lower()[:40] not in own_text:
            logger.info(
                "Dropped a suggestion for %s: evidence was not in their own lines",
                user.id,
            )
            continue
        out.append(
            {
                "category": item.get("category") or "general",
                "said": (item.get("said") or "").strip() or None,
                "suggestion": (item.get("issue") or item.get("suggestion") or "").strip(),
                "better": (item.get("better") or "").strip() or None,
                "evidence": evidence or None,
            }
        )
    return out


LIVE_ANSWER_PROMPT = """You help someone answer a question during a live meeting.

Use only the preparation context provided. Be direct and specific: they are
about to say this out loud.

- Answer in at most three short sentences.
- If the context does not cover the question, say so plainly and suggest what
  to ask instead. Never invent facts, numbers, dates or commitments.
- Write words they can speak, not advice about speaking.
"""

COACH_CHAT_PROMPT = """You answer questions about someone's own meeting coaching.

You are given their preparation, their coaching notes and their own words from
meetings. Answer only from that context.

- Be concrete and practical: they want to improve, not be flattered.
- If the context does not contain the answer, say so rather than guessing.
- Never discuss other participants' performance; this is their private coaching.
"""


async def suggest_live_answer(
    settings: Settings, *, question: str, context: str
) -> str:
    """Draft an answer the user can say now, grounded in their preparation."""
    client = GroqClient(settings)
    reply, _tokens = await client._chat(  # noqa: SLF001
        [
            {"role": "system", "content": LIVE_ANSWER_PROMPT},
            {
                "role": "user",
                "content": f"Preparation context:\n{context}\n\nQuestion asked:\n{question}",
            },
        ],
        temperature=0.3,
    )
    return reply


async def answer_coaching_question(
    settings: Settings,
    *,
    question: str,
    context: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Answer a follow-up about the user's own coaching, from their records."""
    client = GroqClient(settings)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": COACH_CHAT_PROMPT},
        {"role": "system", "content": f"Their records:\n{context}"},
    ]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    reply, _tokens = await client._chat(messages, temperature=0.3)  # noqa: SLF001
    return reply
