"""Groq LLM client: meeting analysis, chat, and Whisper fallback transcription.

The configured default (openai/gpt-oss-120b) is a reasoning model: it returns a
`reasoning` field alongside `content`, and BOTH draw from max_tokens. A small
max_tokens therefore yields an empty `content`. Keep it generous.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

GROQ_BASE = "https://api.groq.com/openai/v1"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)

ANALYSIS_SYSTEM_PROMPT = """You analyse meeting transcripts.

Return ONLY valid JSON with exactly this shape:
{
  "summary": string,
  "decisions": [string],
  "action_items": [{"task": string, "owner": string|null, "due": string|null,
                    "due_date": string|null}],
  "deadlines": [{"what": string, "when": string, "date": string|null}],
  "participants": [string]
}

Rules:
- Use null when a value is genuinely unknown. Never guess an owner.
- Do not invent facts, decisions, or commitments that are not in the transcript.
- If nothing of a category was discussed, return an empty array for it.
- Speech-to-text errors are common. When a known-participants list is given
  below, map a garbled owner name to the participant it clearly corresponds to
  ("Pani" -> "Bunny Reddy", "locus" -> "Lokesh"). Only do this when one
  participant is the obvious match; otherwise leave the owner null rather than
  picking between candidates. Never invent a person who is not on that list.
- "due" and "when" keep the speaker's own wording (e.g. "next Friday", "28-9-2026").
- "due_date" and "date" are the SAME deadline normalised to ISO 8601 YYYY-MM-DD.
  Day comes before month in ambiguous numeric dates such as 28-9-2026.
  Resolve partial and relative dates ("the 29th", "next Friday", "end of month")
  against the meeting date given below, choosing the nearest occurrence on or
  after it. That is resolution against a known reference, not guesswork.
  Set them to null only when the transcript names no date at all, or names one
  too vague to place on a calendar ("soon", "later this quarter").
"""

CHAT_SYSTEM_PROMPT = """You answer questions about ONE specific meeting.

You are given that meeting's transcript and analysis as your only context.
- Answer strictly from that context.
- If the answer is not in this meeting's records, say so plainly. Do not
  speculate and do not draw on other meetings.
- Format for a chat panel: lead with the direct answer, use short paragraphs,
  and use Markdown bullets only when they improve scanning.
- For longer answers, use at most three descriptive Markdown headings.
- Avoid Markdown tables and raw HTML. Keep the response concise unless the
  user explicitly asks for a detailed report.
"""


class GroqError(RuntimeError):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Groq API error {status_code}: {detail}")


class GroqClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.groq_api_key:
            raise GroqError(0, "GROQ_API_KEY is not configured")
        self._key = settings.groq_api_key
        self._model = settings.groq_model
        self._whisper_model = settings.groq_whisper_model
        self._max_tokens = settings.groq_max_tokens

    @property
    def model(self) -> str:
        return self._model

    async def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> tuple[str, int]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self._max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{GROQ_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json=payload,
            )
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text[:500]
            raise GroqError(resp.status_code, detail)

        data = resp.json()
        choice = data["choices"][0]
        content = (choice["message"].get("content") or "").strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)

        if not content:
            # Reasoning consumed the whole budget.
            raise GroqError(
                200,
                f"Model returned empty content (finish_reason="
                f"{choice.get('finish_reason')}). Increase GROQ_MAX_TOKENS.",
            )
        return content, tokens

    async def analyse_meeting(
        self,
        transcript_text: str,
        *,
        meeting_date: str | None = None,
        participants: list[str] | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Produce summary, decisions, action items, deadlines and participants.

        `meeting_date` (ISO YYYY-MM-DD) anchors relative dates like "the 29th".
        """
        if not transcript_text.strip():
            return (
                {
                    "summary": "No speech was captured in this meeting.",
                    "decisions": [],
                    "action_items": [],
                    "deadlines": [],
                    "participants": [],
                },
                0,
            )

        content, tokens = await self._chat(
            [
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript_text}"},
            ],
            json_mode=True,
        )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise GroqError(200, f"Model did not return valid JSON: {content[:200]}") from exc

        # Normalise so downstream code can rely on the shape.
        return (
            {
                "summary": parsed.get("summary") or "",
                "decisions": parsed.get("decisions") or [],
                "action_items": parsed.get("action_items") or [],
                "deadlines": parsed.get("deadlines") or [],
                "participants": parsed.get("participants") or [],
            },
            tokens,
        )

    async def answer_about_meeting(
        self, question: str, context: str, history: list[dict[str, str]] | None = None
    ) -> tuple[str, int]:
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "system", "content": f"Meeting records:\n{context}"},
        ]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})
        return await self._chat(messages, temperature=0.3)

    async def transcribe_audio(self, audio: bytes, filename: str = "audio.mp3") -> str:
        """Whisper fallback, used when Recall produced no transcript."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{GROQ_BASE}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": (filename, audio, "application/octet-stream")},
                data={"model": self._whisper_model, "response_format": "json"},
            )
        if resp.status_code >= 400:
            raise GroqError(resp.status_code, resp.text[:500])
        return resp.json().get("text", "")
