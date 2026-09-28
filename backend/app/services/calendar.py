"""Google OAuth + Recall Calendar V2.

Endpoints and field names verified against the official reference:
  - Create calendar:  POST /api/v2/calendars/
      platform, oauth_client_id, oauth_client_secret, oauth_refresh_token
      https://docs.recall.ai/reference/calendars_create
  - List events:      GET  /api/v2/calendar-events/?calendar_id=...
      https://docs.recall.ai/reference/calendar_events_list
  - Schedule a bot:   POST /api/v2/calendar-events/{id}/bot/
      bot_config, deduplication_key
      https://docs.recall.ai/reference/calendar_events_bot_create

Calendar V2 is app-managed scheduling: Recall syncs the calendar, and this
application decides which events get a bot.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.services.recall import RecallClient, RecallError

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
# Full calendar scope. calendar.events alone can write events, but creating a
# separate "MeetMind AI" calendar (calendars.insert) requires this wider scope.
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
]

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class CalendarError(RuntimeError):
    pass


def build_authorization_url(settings: Settings, state: str) -> str:
    """Google consent URL. access_type=offline is what yields a refresh token."""
    if not settings.google_oauth_ready:
        raise CalendarError(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET."
        )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        # Without this, Google omits refresh_token on repeat authorisations.
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(settings: Settings, code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code >= 400:
        raise CalendarError(f"Google token exchange failed: {resp.text[:300]}")

    tokens = resp.json()
    if not tokens.get("refresh_token"):
        raise CalendarError(
            "Google did not return a refresh_token. Revoke the app's access at "
            "https://myaccount.google.com/permissions and authorise again."
        )
    return tokens


async def fetch_google_email(access_token: str) -> str | None:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        return None
    return resp.json().get("email")


class RecallCalendarClient(RecallClient):
    """Calendar V2 operations, sharing the base client's auth and error handling."""

    async def create_calendar(
        self,
        *,
        oauth_client_id: str,
        oauth_client_secret: str,
        oauth_refresh_token: str,
        platform: str = "google_calendar",
        oauth_email: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "platform": platform,
            "oauth_client_id": oauth_client_id,
            "oauth_client_secret": oauth_client_secret,
            "oauth_refresh_token": oauth_refresh_token,
        }
        if oauth_email:
            payload["oauth_email"] = oauth_email
        return await self._request("POST", "/api/v2/calendars/", json=payload)

    async def get_calendar(self, calendar_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v2/calendars/{calendar_id}/")

    async def delete_calendar(self, calendar_id: str) -> Any:
        return await self._request("DELETE", f"/api/v2/calendars/{calendar_id}/")

    async def list_events(
        self,
        calendar_id: str,
        *,
        start_time_gte: str | None = None,
        start_time_lte: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"calendar_id": calendar_id}
        if start_time_gte:
            params["start_time__gte"] = start_time_gte
        if start_time_lte:
            params["start_time__lte"] = start_time_lte

        data = await self._request("GET", "/api/v2/calendar-events/", params=params)
        return data.get("results", []) if isinstance(data, dict) else []

    async def schedule_bot(
        self,
        event_id: str,
        *,
        bot_name: str,
        transcription: bool = True,
        deduplication_key: str | None = None,
    ) -> dict[str, Any]:
        """Attach a bot to a calendar event. Recall joins it at start time."""
        bot_config: dict[str, Any] = {"bot_name": bot_name}
        if transcription:
            bot_config["recording_config"] = {
                "transcript": {
                    "provider": {
                        "recallai_streaming": {
                            "mode": "prioritize_accuracy",
                            "language_code": "en",
                        }
                    }
                }
            }

        payload: dict[str, Any] = {"bot_config": bot_config}
        if deduplication_key:
            payload["deduplication_key"] = deduplication_key

        return await self._request(
            "POST", f"/api/v2/calendar-events/{event_id}/bot/", json=payload
        )

    async def unschedule_bot(self, event_id: str) -> Any:
        return await self._request("DELETE", f"/api/v2/calendar-events/{event_id}/bot/")


__all__ = [
    "CalendarError",
    "RecallCalendarClient",
    "RecallError",
    "build_authorization_url",
    "exchange_code_for_tokens",
    "fetch_google_email",
]


# --- Writing events back to Google --------------------------------------

GOOGLE_CAL_API = "https://www.googleapis.com/calendar/v3"
MEETMIND_CALENDAR_NAME = "MeetMind AI"


def events_url(calendar_id: str = "primary") -> str:
    from urllib.parse import quote

    return f"{GOOGLE_CAL_API}/calendars/{quote(calendar_id, safe='')}/events"


async def refresh_access_token(settings: Settings, refresh_token: str) -> str:
    """Exchange a stored refresh token for a short-lived access token."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code >= 400:
        raise CalendarError(
            "Could not refresh the Google access token. Reconnect the calendar. "
            f"({resp.text[:200]})"
        )
    token = resp.json().get("access_token")
    if not token:
        raise CalendarError("Google returned no access token.")
    return token


async def create_all_day_event(
    access_token: str,
    *,
    summary: str,
    date_iso: str,
    description: str | None = None,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """Create an all-day event on the primary calendar.

    Google treats all-day `end.date` as exclusive, so a single-day event ends
    on the following day.
    """
    from datetime import date, timedelta

    start = date.fromisoformat(date_iso)
    body: dict[str, Any] = {
        "summary": summary,
        "start": {"date": start.isoformat()},
        "end": {"date": (start + timedelta(days=1)).isoformat()},
        "transparency": "transparent",
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 24 * 60}],
        },
    }
    if description:
        body["description"] = description

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            events_url(calendar_id),
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
        )
    if resp.status_code >= 400:
        detail = resp.text[:300]
        if resp.status_code == 403 and "insufficient" in detail.lower():
            raise CalendarError(
                "The connected calendar is read-only. Reconnect it to grant "
                "write access so deadlines can be added."
            )
        raise CalendarError(f"Google rejected the event: {detail}")
    return resp.json()


async def delete_event(
    access_token: str, event_id: str, calendar_id: str = "primary"
) -> None:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.delete(
            f"{events_url(calendar_id)}/{event_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    # 410 = already gone, which is the outcome we wanted anyway.
    if resp.status_code >= 400 and resp.status_code not in (404, 410):
        raise CalendarError(f"Could not delete the event: {resp.text[:200]}")


async def ensure_meetmind_calendar(access_token: str) -> str:
    """Return the id of the dedicated MeetMind calendar, creating it if absent.

    Keeps generated deadlines off the user's primary calendar, so they can be
    toggled or deleted as a group without touching their own events.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        listing = await client.get(
            f"{GOOGLE_CAL_API}/users/me/calendarList",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if listing.status_code == 403:
            raise CalendarError(
                "The connected account has not granted permission to manage "
                "calendars. Reconnect Google Calendar to grant it."
            )
        if listing.status_code < 400:
            for entry in listing.json().get("items", []):
                if (entry.get("summary") or "").strip() == MEETMIND_CALENDAR_NAME:
                    return entry["id"]

        created = await client.post(
            f"{GOOGLE_CAL_API}/calendars",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "summary": MEETMIND_CALENDAR_NAME,
                "description": (
                    "Deadlines and action items extracted from your meetings by "
                    "MeetMind AI."
                ),
            },
        )
    if created.status_code >= 400:
        raise CalendarError(
            f"Could not create the MeetMind calendar: {created.text[:250]}"
        )
    return created.json()["id"]
