"""Reading the mail that matters, and turning it into the same objects a
meeting produces.

The point is not to be an inbox. It is that a commitment made over email -
"I'll send the revised scope by Friday" - is the same thing PromiseMirror
already tracks from meetings, and a date quietly changed in a reply should
trip the same alarm as one quietly changed in a call.

Scope is deliberately narrow: only mail from senders the user named. Nothing
else is fetched, and message bodies are never stored.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

import httpx

from app.config import Settings
from app.services.groq_client import GroqClient, GroqError

logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
# Enough of a message to summarise without shipping an entire thread to the
# model, and without us holding more of someone's mail than we need.
BODY_CHARS = 6000


class MailboxError(RuntimeError):
    pass


@dataclass
class FetchedEmail:
    gmail_id: str
    thread_id: str | None
    sender: str
    sender_name: str | None
    subject: str | None
    received_at: datetime | None
    body: str
    matched_pattern: str


def matches(sender: str, patterns: list[str]) -> str | None:
    """Which priority rule this sender matches, if any.

    A bare domain matches anything at that domain; anything containing "@" is
    treated as a full address and must match exactly. Subdomains are matched
    too, so "acme.com" covers "mail.acme.com".
    """
    address = parseaddr(sender)[1].strip().lower()
    if not address or "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1]
    for raw in patterns:
        p = raw.strip().lower().lstrip("@")
        if not p:
            continue
        if "@" in p:
            if address == p:
                return raw
        elif domain == p or domain.endswith(f".{p}"):
            return raw
    return None


def _header(payload: dict[str, Any], name: str) -> str | None:
    for h in payload.get("headers") or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def _decode(data: str | None) -> str:
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
    except Exception:  # pragma: no cover - malformed part
        return ""


def extract_body(payload: dict[str, Any]) -> str:
    """Plain text from a Gmail payload, preferring text/plain over HTML."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        return _decode((payload.get("body") or {}).get("data"))

    parts = payload.get("parts") or []
    # Depth-first, plain text wins; HTML is a fallback with tags stripped.
    plain = [extract_body(p) for p in parts if p.get("mimeType") == "text/plain"]
    text = "\n".join(t for t in plain if t).strip()
    if text:
        return text
    for part in parts:
        if part.get("mimeType", "").startswith("multipart/"):
            nested = extract_body(part)
            if nested:
                return nested
    html = "\n".join(
        _decode((p.get("body") or {}).get("data"))
        for p in parts
        if p.get("mimeType") == "text/html"
    )
    if html:
        import re

        return re.sub(r"<[^>]+>", " ", html)
    if mime == "text/html":
        import re

        return re.sub(r"<[^>]+>", " ", _decode((payload.get("body") or {}).get("data")))
    return ""


def _gmail_query(patterns: list[str], days: int) -> str:
    """Ask Gmail for only the senders we care about.

    Filtering server-side matters: it is the difference between reading the
    user's whole mailbox and reading the handful of messages they asked us to
    watch.
    """
    froms = " OR ".join(f"from:{p.strip().lstrip('@')}" for p in patterns if p.strip())
    return f"({froms}) newer_than:{days}d"


async def fetch_priority_mail(
    access_token: str,
    *,
    patterns: list[str],
    days: int = 14,
    limit: int = 25,
) -> list[FetchedEmail]:
    """Recent messages from the named senders. Nothing else is requested."""
    if not patterns:
        return []

    headers = {"Authorization": f"Bearer {access_token}"}
    out: list[FetchedEmail] = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        listing = await client.get(
            f"{GMAIL_API}/messages",
            headers=headers,
            params={"q": _gmail_query(patterns, days), "maxResults": limit},
        )
        if listing.status_code == 403:
            raise MailboxError(
                "Google refused Gmail access. The gmail.readonly scope has to be "
                "added to the OAuth consent screen, and the calendar reconnected "
                "so the new permission is granted."
            )
        if listing.status_code >= 400:
            raise MailboxError(f"Gmail list failed ({listing.status_code}).")

        for stub in listing.json().get("messages") or []:
            detail = await client.get(
                f"{GMAIL_API}/messages/{stub['id']}",
                headers=headers,
                params={"format": "full"},
            )
            if detail.status_code >= 400:
                logger.warning("Skipping message %s (%s)", stub["id"], detail.status_code)
                continue
            msg = detail.json()
            payload = msg.get("payload") or {}
            raw_from = _header(payload, "From") or ""
            matched = matches(raw_from, patterns)
            if matched is None:
                # Gmail's from: is fuzzier than our rules; ours decide.
                continue
            name, address = parseaddr(raw_from)
            received = None
            date_header = _header(payload, "Date")
            if date_header:
                try:
                    received = parsedate_to_datetime(date_header)
                    if received.tzinfo is None:
                        received = received.replace(tzinfo=UTC)
                except Exception:  # pragma: no cover - unparseable date
                    received = None
            out.append(
                FetchedEmail(
                    gmail_id=msg["id"],
                    thread_id=msg.get("threadId"),
                    sender=address.lower(),
                    sender_name=name or None,
                    subject=_header(payload, "Subject"),
                    received_at=received,
                    body=extract_body(payload)[:BODY_CHARS],
                    matched_pattern=matched,
                )
            )
    return out


SUMMARY_PROMPT = """You triage one email for a busy founder.

Return ONLY valid JSON:
{
  "summary": string,
  "highlights": [string],
  "urgent": boolean,
  "urgency_reason": string|null,
  "commitments": [{"text": string, "owner": string|null, "due": string|null,
                   "due_date": string|null}]
}

Rules:
- "summary" is at most two sentences, saying what this email is actually for.
- "highlights" are at most four short lines: decisions, asks, numbers, dates.
  Quote figures and dates exactly. No filler like "the sender says hello".
- "urgent" is true only when something is time-sensitive or the sender is
  blocked waiting on a reply. A newsletter is never urgent. If false,
  "urgency_reason" is null.
- "commitments" are promises made IN THIS EMAIL, by either side. Use the
  sender's own wording in "text". "owner" is who owes it, or null if unclear -
  never guess. "due" keeps their wording; "due_date" is the same date as
  ISO 8601 YYYY-MM-DD, resolved against the email's date, or null if no date
  is given. Return an empty list when nothing was promised.
- Never invent facts, dates or commitments that are not in the email.
"""


async def understand(
    settings: Settings, email: FetchedEmail
) -> dict[str, Any]:
    """Summarise one email and pull out any promises it contains."""
    received = (
        email.received_at.date().isoformat() if email.received_at else "unknown"
    )
    content = (
        f"Email date: {received}\n"
        f"From: {email.sender_name or ''} <{email.sender}>\n"
        f"Subject: {email.subject or '(no subject)'}\n\n"
        f"{email.body}"
    )
    client = GroqClient(settings)
    try:
        return await client.json_completion(SUMMARY_PROMPT, content)
    except GroqError as exc:
        logger.warning("Could not summarise %s: %s", email.gmail_id, exc.detail)
        return {
            "summary": None,
            "highlights": [],
            "urgent": False,
            "urgency_reason": None,
            "commitments": [],
        }
