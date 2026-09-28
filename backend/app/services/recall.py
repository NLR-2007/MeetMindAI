"""Thin async client for the Recall.ai REST API.

Field names and paths follow the official docs:
  - Regions / base URL:  https://docs.recall.ai/docs/regions
  - Create Bot:          https://docs.recall.ai/reference/bot_create
  - Retrieve Bot:        https://docs.recall.ai/reference/bot_retrieve
  - Transcription:       https://docs.recall.ai/docs/transcription
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class RecallError(RuntimeError):
    """Recall.ai returned a non-success response."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Recall API error {status_code}: {detail}")


class RecallClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.recall_api_base
        self._language = settings.transcription_language
        self._headers = {
            # Recall uses token auth, not Bearer.
            "Authorization": f"Token {settings.recall_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.request(method, url, headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text[:500]
            logger.error("Recall %s %s -> %s %s", method, path, resp.status_code, detail)
            raise RecallError(resp.status_code, detail)
        if not resp.content:
            return None
        return resp.json()

    async def create_bot(
        self,
        meeting_url: str,
        bot_name: str,
        *,
        transcription: bool = True,
        realtime_webhook_url: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send a bot to a meeting. POST /api/v1/bot/ -> 201 Bot."""
        recording_config: dict[str, Any] = {}

        if transcription:
            # recallai_streaming is Recall's own STT provider.
            recording_config["transcript"] = {
                "provider": {
                    "recallai_streaming": {
                        "mode": "prioritize_low_latency",
                        "language_code": self._language,
                    }
                }
            }

        if realtime_webhook_url:
            # Realtime endpoints are per-bot and cannot be set in the dashboard.
            recording_config["realtime_endpoints"] = [
                {
                    "type": "webhook",
                    "url": realtime_webhook_url,
                    "events": ["transcript.data"],
                }
            ]

        payload: dict[str, Any] = {"meeting_url": meeting_url, "bot_name": bot_name}
        if recording_config:
            payload["recording_config"] = recording_config
        if metadata:
            payload["metadata"] = metadata

        return await self._request("POST", "/api/v1/bot/", json=payload)

    async def get_bot(self, bot_id: str) -> dict[str, Any]:
        """GET /api/v1/bot/{id}/"""
        return await self._request("GET", f"/api/v1/bot/{bot_id}/")

    async def leave_call(self, bot_id: str) -> Any:
        """POST /api/v1/bot/{id}/leave_call/"""
        return await self._request("POST", f"/api/v1/bot/{bot_id}/leave_call/")


def latest_status(bot: dict[str, Any]) -> str | None:
    """Pull the most recent status code out of a Bot object.

    Recall returns an append-only `status_changes` list; the last entry is current.
    """
    changes = bot.get("status_changes") or []
    if changes:
        return changes[-1].get("code")
    status = bot.get("status")
    if isinstance(status, dict):
        return status.get("code")
    return None
