"""MeetMind AI — FastAPI application entrypoint."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.config import get_settings
from app.routers import (
    auth,
    calendar,
    chat,
    markup,
    meetings,
    promisemirror,
    webhooks,
    team,
)
from app.services import memory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("meetmind")

try:
    settings = get_settings()
except ValidationError as exc:  # pragma: no cover - startup guard
    raise SystemExit(
        "Environment validation failed. Copy .env.example to .env and fill it in.\n"
        f"{exc}"
    ) from exc


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.db import init_db

    init_db()
    logger.info("Database ready (region=%s)", settings.recall_region)
    if not settings.recall_webhook_secret:
        logger.warning(
            "RECALL_WEBHOOK_SECRET is not set: webhooks will be rejected. "
            "Create a workspace secret in the Recall dashboard."
        )

    hindsight_server = _start_hindsight()
    try:
        yield
    finally:
        if hindsight_server is not None:
            try:
                hindsight_server.stop()
                logger.info("Hindsight server stopped")
            except Exception:
                logger.exception("Failed to stop the Hindsight server cleanly")


def _start_hindsight():
    """Connect to Hindsight, starting an embedded server if none is given.

    Any failure is logged and the app continues on the MySQL memory backend:
    losing semantic recall degrades chat, it should not take the service down.
    """
    from app.services import memory as memory_module

    if not settings.hindsight_enabled:
        logger.info("Memory backend: mysql (Hindsight not enabled)")
        return None

    try:
        from hindsight import HindsightServer
    except ImportError:
        logger.error(
            "MEMORY_BACKEND=hindsight but the hindsight package is not installed. "
            "Run: pip install hindsight-all. Falling back to MySQL."
        )
        return None

    server = None
    try:
        if settings.hindsight_base_url:
            base_url = settings.hindsight_base_url
        else:
            if not settings.hindsight_key:
                logger.error(
                    "Hindsight needs an LLM key: set HINDSIGHT_LLM_API_KEY or "
                    "GROQ_API_KEY. Falling back to MySQL."
                )
                return None
            # Free Groq orgs reject service_tier=auto, which is Hindsight's
            # default for that provider.
            os.environ.setdefault("HINDSIGHT_API_LLM_GROQ_SERVICE_TIER", "on_demand")
            logger.info("Starting embedded Hindsight server (this takes ~20s)…")
            kwargs = {
                "llm_provider": settings.hindsight_llm_provider,
                "llm_model": settings.hindsight_llm_model,
                "llm_api_key": settings.hindsight_key,
                "log_level": "warning",
            }
            if settings.hindsight_llm_base_url:
                kwargs["llm_base_url"] = settings.hindsight_llm_base_url
            server = HindsightServer(**kwargs)
            # Model loading needs far longer than the 30s default.
            server.start(timeout=300.0)
            base_url = server.url

        memory_module.set_hindsight_base_url(base_url)
        logger.info("Memory backend: hindsight (%s)", base_url)
        return server
    except Exception:
        logger.exception("Hindsight failed to start; falling back to MySQL memory")
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass
        return None


app = FastAPI(
    title="MeetMind AI",
    description=(
        "AI-powered meeting assistant. Bots record and transcribe meetings only "
        "after explicit user confirmation."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(meetings.router)
app.include_router(chat.router)
app.include_router(webhooks.router)
app.include_router(calendar.router)
app.include_router(promisemirror.router)
app.include_router(markup.router)
app.include_router(team.router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, object]:
    """Liveness plus a redacted view of what config the app actually loaded."""
    db_ok = False
    try:
        from sqlalchemy import text

        from app.db import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # pragma: no cover - diagnostic path
        logger.warning("Database health check failed: %s", exc)

    return {
        "status": "ok",
        "recall_region": settings.recall_region,
        "recall_api_base": settings.recall_api_base,
        "recall_api_key_present": bool(settings.recall_api_key),
        "recall_webhook_secret_present": bool(settings.recall_webhook_secret),
        "database_configured": settings.database_url is not None,
        "database_reachable": db_ok,
        "groq_configured": settings.groq_api_key is not None,
        "groq_model": settings.groq_model,
        "google_oauth_ready": settings.google_oauth_ready,
        "memory_backend": (
            "hindsight" if memory.hindsight_active() else "mysql"
        ),
        "memory_backend_requested": settings.memory_backend,
        # Reports what is actually wired up, never what was merely configured.
        "hindsight_integrated": memory.hindsight_active(),
        "public_base_url": settings.public_base_url,
    }
