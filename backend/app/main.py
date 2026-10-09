"""MeetMind AI — FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
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
    inbox,
    markup,
    meetings,
    promisemirror,
    teams,
    webhooks,
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

    # A database that is merely not running yet must not kill the process.
    # /health is built to report `database_reachable: false`, and the frontend
    # shows a "cannot reach the backend" banner — if the app exits here, the
    # user is told to start the API they already started, and never learns
    # that MySQL is the thing that is down.
    try:
        init_db()
        logger.info("Database ready (region=%s)", settings.recall_region)
    except Exception as exc:
        logger.error(
            "Database unreachable at startup: %s\n"
            "The API will serve /health and /memory/status so you can see this, "
            "but every data endpoint will fail until the database is up. "
            "Start MySQL (XAMPP > MySQL > Start), then restart this process.",
            exc,
        )
    if not settings.recall_webhook_secret:
        logger.warning(
            "RECALL_WEBHOOK_SECRET is not set: webhooks will be rejected. "
            "Create a workspace secret in the Recall dashboard."
        )

    hindsight_server = _start_hindsight()

    # An external Hindsight server takes minutes to load its models, and is
    # usually started alongside this process rather than before it. Probing
    # once at startup therefore reports "unreachable" for the rest of the run
    # even after Hindsight comes up, and the only cure was restarting the API.
    # Keep retrying in the background instead, so the two can start in any
    # order and the wiring converges on its own.
    watcher: asyncio.Task | None = None
    if (
        hindsight_server is None
        and settings.hindsight_enabled
        and settings.hindsight_base_url
        and not memory.hindsight_active()
    ):
        watcher = asyncio.create_task(
            _await_hindsight(settings.hindsight_base_url.rstrip("/"))
        )

    try:
        yield
    finally:
        if watcher is not None:
            watcher.cancel()
        if hindsight_server is not None:
            try:
                hindsight_server.stop()
                logger.info("Hindsight server stopped")
            except Exception:
                logger.exception("Failed to stop the Hindsight server cleanly")


async def _await_hindsight(
    base_url: str, every: float = 15.0, give_up_after: float = 1800.0
) -> None:
    """Wire Hindsight up as soon as it starts answering.

    Runs off the event loop thread for the probe itself, so a hanging server
    cannot stall request handling. Gives up after a while rather than polling
    a URL that is never going to answer for the life of the process.
    """
    from app.services import memory as memory_module

    waited = 0.0
    while waited < give_up_after:
        await asyncio.sleep(every)
        waited += every
        if memory_module.hindsight_active():
            return
        if await asyncio.to_thread(_hindsight_reachable, base_url, 5.0):
            memory_module.set_hindsight_base_url(base_url)
            logger.info(
                "Hindsight became reachable at %s after %.0fs; memory backend "
                "is now hindsight",
                base_url,
                waited,
            )
            return
    logger.warning(
        "Hindsight at %s never answered within %.0fs; staying on MySQL memory.",
        base_url,
        give_up_after,
    )


def _hindsight_reachable(base_url: str, timeout: float = 5.0) -> bool:
    """Does a Hindsight server actually answer at this URL?

    Startup only, so a blocking call is fine here and keeps the check simple.
    """
    try:
        import httpx

        resp = httpx.get(f"{base_url}/v1/default/banks", timeout=timeout)
        return resp.status_code < 500
    except Exception as exc:
        logger.debug("Hindsight probe of %s failed: %s", base_url, exc)
        return False


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
            base_url = settings.hindsight_base_url.rstrip("/")
            # A configured URL is not a running server. Without this probe,
            # /health and /memory/status report "hindsight_integrated": true
            # purely because an env var is set, while every recall silently
            # falls back to MySQL — the exact claim those endpoints promise
            # never to make.
            if not _hindsight_reachable(base_url):
                logger.error(
                    "HINDSIGHT_BASE_URL=%s is not answering. Falling back to "
                    "MySQL memory. Start the Hindsight server, or unset "
                    "HINDSIGHT_BASE_URL to let MeetMind start its own.",
                    base_url,
                )
                return None
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
            except Exception:  # pragma: no cover - best-effort cleanup
                logger.debug("Hindsight stop failed during cleanup", exc_info=True)
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
app.include_router(teams.router)
app.include_router(inbox.router)


@app.get("/memory/status", tags=["system"])
async def memory_status() -> dict[str, object]:
    """Public, verifiable answer to "is Hindsight actually running?".

    Reports the live wiring rather than configuration: if Hindsight is
    unreachable this says "mysql", never the backend that was merely asked for.
    """
    active = memory.hindsight_active()
    bank_count: int | None = None
    if active:
        try:
            import httpx

            base = memory.hindsight_base_url()
            # Async client: a sync call here would block the event loop for the
            # whole timeout, stalling every other request if Hindsight hangs.
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{base}/v1/default/banks")
            if resp.status_code < 400:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("banks") or []
                bank_count = len(items)
        except Exception:  # pragma: no cover - diagnostic only
            logger.debug("Could not count Hindsight banks", exc_info=True)

    return {
        "backend": "hindsight" if active else "mysql",
        "hindsight_integrated": active,
        "requested": settings.memory_backend,
        "llm_provider": settings.hindsight_llm_provider if active else None,
        "llm_model": settings.hindsight_llm_model if active else None,
        "memory_banks": bank_count,
        "note": (
            "Semantic recall across meetings, persisted outside the app."
            if active
            else "Hindsight unavailable; using the lexical MySQL fallback."
        ),
    }


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
        # "ok" means the process is serving. It is not a claim that every
        # dependency is healthy: read the specific flags for that.
        "status": "ok" if db_ok else "degraded",
        "hint": (
            None
            if db_ok
            else "Database unreachable. Start MySQL (XAMPP > MySQL > Start), "
            "then restart the API."
        ),
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
