"""MemoryService — persistent memory behind a stable interface.

Hindsight is NOT integrated. `MySQLMemoryService` is the working implementation
and MySQL is explicitly temporary storage. When Hindsight is ready, add a
`HindsightMemoryService` implementing the same ABC and swap the factory below;
no chat or meeting code needs to change.
"""
from __future__ import annotations

import abc
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory

logger = logging.getLogger(__name__)

_PUNCTUATION = str.maketrans({c: " " for c in "?!.,;:\"'()[]{}<>/\\"})


def _normalise(text: str) -> str:
    return text.translate(_PUNCTUATION).lower()


def _keywords(query: str) -> set[str]:
    """Content words worth matching on, stripped of punctuation."""
    return {w for w in _normalise(query).split() if len(w) > 3}


class MemoryService(abc.ABC):
    """Interface every memory backend must satisfy."""

    @abc.abstractmethod
    def save_memory(
        self,
        content: str,
        *,
        scope: str = "meeting",
        scope_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist a memory. Returns the memory id."""

    @abc.abstractmethod
    def recall_memory(
        self,
        query: str,
        *,
        scope: str = "meeting",
        scope_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return memories relevant to `query`, newest-first within scope."""


class MySQLMemoryService(MemoryService):
    """Temporary MySQL-backed implementation.

    Recall is keyword/LIKE based, not semantic. That is a deliberate stopgap:
    semantic retrieval is what Hindsight will provide.
    """

    backend_name = "mysql"
    is_persistent_memory_backend = False  # Hindsight not connected.

    def __init__(self, db: Session) -> None:
        self._db = db

    def save_memory(
        self,
        content: str,
        *,
        scope: str = "meeting",
        scope_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        # Re-analysing a meeting re-saves the same summary and decisions, so
        # identical content within a scope is a no-op rather than a new row.
        existing = self._db.scalar(
            select(Memory).where(
                Memory.scope == scope,
                Memory.scope_id == scope_id,
                Memory.content == content,
            )
        )
        if existing is not None:
            logger.debug("memory already present in %s/%s", scope, scope_id)
            return existing.id

        memory = Memory(scope=scope, scope_id=scope_id, content=content, meta=metadata)
        self._db.add(memory)
        self._db.flush()
        logger.debug("saved memory %s in %s/%s", memory.id, scope, scope_id)
        return memory.id

    def recall_memory(
        self,
        query: str,
        *,
        scope: str = "meeting",
        scope_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(Memory)
            .where(Memory.scope == scope, Memory.scope_id == scope_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        rows = list(self._db.scalars(stmt))

        # Cheap lexical ranking so the most on-topic memories come first.
        # Punctuation is stripped: without it "deadline?" never matches the
        # stored word "deadline".
        terms = _keywords(query)
        if terms:
            rows.sort(
                key=lambda m: sum(t in _normalise(m.content) for t in terms),
                reverse=True,
            )

        return [
            {
                "id": m.id,
                "content": m.content,
                "metadata": m.meta,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ]


class HindsightMemoryService(MemoryService):
    """Hindsight-backed agent memory.

    Maps this application's (scope, scope_id) onto a Hindsight *bank*, so a
    meeting's memories stay isolated exactly as they were under MySQL, while
    recall becomes semantic rather than lexical.

    The client is injected rather than constructed here so the server lifecycle
    stays with the application, not with a per-request dependency.
    """

    backend_name = "hindsight"
    is_persistent_memory_backend = True

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def _call(self, method: str, **kwargs: Any) -> Any:
        """Run a Hindsight client call on its own thread and event loop.

        Two constraints force this shape:
        1. The sync client calls asyncio.run() internally, which raises
           "This event loop is already running" inside a FastAPI request.
        2. Its aiohttp session binds to whichever loop created it, so a client
           built on the request loop cannot be reused on a worker thread.

        Building the client inside the worker thread satisfies both.
        """
        def run() -> Any:
            from hindsight import HindsightClient

            client = HindsightClient(base_url=self._base_url)
            return getattr(client, method)(**kwargs)

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=60)

    @staticmethod
    def bank_id(scope: str, scope_id: str) -> str:
        """One bank per scope, e.g. meeting-<id>, project-<id>, user-<id>."""
        return f"{scope}-{scope_id}"

    def save_memory(
        self,
        content: str,
        *,
        scope: str = "meeting",
        scope_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        bank = self.bank_id(scope, scope_id)
        # retain_async queues the fact-extraction LLM work on Hindsight's own
        # worker instead of blocking the request. A meeting writes ~8 memories;
        # done synchronously that is minutes of LLM time per processing run.
        result = self._call("retain", bank_id=bank, content=content, retain_async=True)
        memory_id = getattr(result, "id", None) or bank
        logger.debug("retained memory in bank %s", bank)
        return str(memory_id)

    def recall_memory(
        self,
        query: str,
        *,
        scope: str = "meeting",
        scope_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        bank = self.bank_id(scope, scope_id)
        try:
            results = self._call("recall", bank_id=bank, query=query)
        except Exception:
            # Memory is an enhancement to chat, never a prerequisite for it.
            logger.exception("Hindsight recall failed for bank %s", bank)
            return []

        items = (
            getattr(results, "results", None)
            or getattr(results, "memories", None)
            or (results if isinstance(results, list) else [])
        )

        out: list[dict[str, Any]] = []
        for item in items[:limit]:
            content = (
                getattr(item, "text", None)
                or getattr(item, "content", None)
                or (item.get("text") or item.get("content") if isinstance(item, dict) else None)
                or str(item)
            )
            out.append({"id": str(getattr(item, "id", "")), "content": content,
                        "metadata": None, "created_at": None})
        return out


# Set once at application startup when the Hindsight backend is active.
_hindsight_base_url: str | None = None


def set_hindsight_base_url(base_url: str | None) -> None:
    global _hindsight_base_url
    _hindsight_base_url = base_url


def hindsight_active() -> bool:
    """True only when a live Hindsight client is actually wired up.

    Deliberately reports reality rather than configuration, so nothing can
    claim Hindsight is integrated while it is merely requested.
    """
    return _hindsight_base_url is not None


def get_memory_service(db: Session) -> MemoryService:
    """Return the active memory backend.

    Falls back to MySQL when Hindsight is configured but not reachable, so a
    memory outage degrades chat quality instead of breaking it.
    """
    if _hindsight_base_url is not None:
        return HindsightMemoryService(_hindsight_base_url)
    return MySQLMemoryService(db)
