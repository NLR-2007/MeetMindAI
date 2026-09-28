"""Environment configuration and validation.

Fails fast at import time if required variables are missing, so the app never
starts in a half-configured state.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root holds the single .env shared by backend tooling.
REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_REGIONS = {
    "us-west-2",
    "us-east-1",
    "eu-central-1",
    "ap-northeast-1",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    recall_api_key: str = Field(min_length=10)
    recall_region: str = "us-west-2"
    # Workspace verification secret (whsec_...) from
    # Developers > API Keys & Secrets > Create Workspace Secret.
    recall_webhook_secret: str | None = None
    # Local-dev escape hatch. Never enable in a deployed environment.
    allow_unverified_webhooks: bool = False

    # Not required for the join milestone; validated when those features land.
    database_url: str | None = None

    # --- Groq ---
    groq_api_key: str | None = None
    # Reasoning model: it emits a `reasoning` field alongside `content`, so keep
    # max_tokens generous or the reasoning budget starves the actual answer.
    groq_model: str = "openai/gpt-oss-120b"
    groq_whisper_model: str = "whisper-large-v3"
    groq_max_tokens: int = 4096

    # --- Authentication ---
    # Generated per-process if unset, which invalidates tokens on restart.
    jwt_secret: str = ""
    jwt_expire_minutes: int = 60 * 24 * 7
    # Meetings created before authentication existed are attached to this user.
    # .local is a reserved domain that email validation rejects.
    default_user_email: str = "demo@meetmind.app"

    # --- Persistent memory ---
    # "mysql" (temporary stopgap) or "hindsight" (real agent memory).
    memory_backend: str = "mysql"
    # Set to reuse an already-running Hindsight server. Left empty, the app
    # starts an embedded one at startup.
    hindsight_base_url: str | None = None
    hindsight_llm_provider: str = "openai"
    hindsight_llm_model: str = "openai/gpt-oss-20b"
    # NVIDIA NIM (or any OpenAI-compatible endpoint).
    hindsight_llm_base_url: str | None = None
    # Falls back to GROQ_API_KEY when unset.
    hindsight_llm_api_key: str | None = None

    # --- Google Calendar OAuth ---
    # The client ID is public by design; the secret is not.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_redirect_uri: str = "http://localhost:8000/calendar/oauth/callback"

    bot_name: str = "MeetMind AI Notetaker"
    # Recall's "auto" detection can flip mid-meeting on accented English and
    # start emitting another script entirely. Pin the language instead.
    transcription_language: str = "en"
    # Public base URL used to build webhook callbacks (ngrok in local dev).
    public_base_url: str | None = None
    cors_origins: str = "http://localhost:3000"

    @field_validator("recall_region")
    @classmethod
    def _check_region(cls, v: str) -> str:
        if v not in VALID_REGIONS:
            raise ValueError(
                f"RECALL_REGION must be one of {sorted(VALID_REGIONS)}, got {v!r}"
            )
        return v

    @property
    def recall_api_base(self) -> str:
        """Regional base URL. Each Recall region is a separate deployment."""
        return f"https://{self.recall_region}.recall.ai"

    @property
    def hindsight_enabled(self) -> bool:
        return self.memory_backend.strip().lower() == "hindsight"

    @property
    def hindsight_key(self) -> str | None:
        """Dedicated memory key if given, otherwise reuse the Groq key."""
        return self.hindsight_llm_api_key or self.groq_api_key

    @property
    def google_oauth_ready(self) -> bool:
        """Calendar scheduling needs BOTH halves of the OAuth client."""
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    if not settings.jwt_secret:
        import logging
        import secrets

        settings.jwt_secret = secrets.token_urlsafe(48)
        logging.getLogger(__name__).warning(
            "JWT_SECRET is not set; generated an ephemeral one. Every restart "
            "will sign users out. Set JWT_SECRET in .env for stable sessions."
        )
    return settings
