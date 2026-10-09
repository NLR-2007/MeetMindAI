"""Hindsight wiring converges whichever order the two processes start in.

Hindsight loads its models for minutes, and is normally started alongside the
API rather than before it. Probing once at startup meant the API reported
"MySQL fallback - Hindsight unreachable" for the whole run even after
Hindsight came up, and only a restart fixed it.
"""
from __future__ import annotations

import asyncio

import pytest

import app.main as main_module
from app.services import memory as memory_module


@pytest.fixture(autouse=True)
def _reset_memory_wiring():
    before = memory_module.hindsight_base_url()
    yield
    memory_module.set_hindsight_base_url(before)


@pytest.mark.asyncio
async def test_watcher_wires_hindsight_up_once_it_answers(monkeypatch) -> None:
    memory_module.set_hindsight_base_url(None)
    assert memory_module.hindsight_active() is False

    # Unreachable for the first two probes, then it finishes loading.
    probes = {"n": 0}

    def fake_probe(base_url: str, timeout: float = 5.0) -> bool:
        probes["n"] += 1
        return probes["n"] >= 3

    monkeypatch.setattr(main_module, "_hindsight_reachable", fake_probe)

    await main_module._await_hindsight(
        "http://memory.test:8888", every=0.01, give_up_after=5.0
    )

    assert probes["n"] == 3
    assert memory_module.hindsight_active() is True
    assert memory_module.hindsight_base_url() == "http://memory.test:8888"


@pytest.mark.asyncio
async def test_watcher_gives_up_rather_than_polling_forever(monkeypatch) -> None:
    memory_module.set_hindsight_base_url(None)
    monkeypatch.setattr(main_module, "_hindsight_reachable", lambda *a, **k: False)

    await main_module._await_hindsight(
        "http://memory.test:8888", every=0.01, give_up_after=0.05
    )

    # Still on the fallback, and crucially it returned instead of hanging.
    assert memory_module.hindsight_active() is False


@pytest.mark.asyncio
async def test_watcher_stops_if_something_else_wired_it_up(monkeypatch) -> None:
    memory_module.set_hindsight_base_url(None)
    calls = {"n": 0}

    def fake_probe(base_url: str, timeout: float = 5.0) -> bool:
        calls["n"] += 1
        return False

    monkeypatch.setattr(main_module, "_hindsight_reachable", fake_probe)

    async def wire_soon() -> None:
        await asyncio.sleep(0.02)
        memory_module.set_hindsight_base_url("http://elsewhere.test:8888")

    await asyncio.gather(
        main_module._await_hindsight(
            "http://memory.test:8888", every=0.01, give_up_after=2.0
        ),
        wire_soon(),
    )

    # It must not overwrite a URL someone else established.
    assert memory_module.hindsight_base_url() == "http://elsewhere.test:8888"


@pytest.mark.asyncio
async def test_watcher_is_cancellable(monkeypatch) -> None:
    """Shutdown must not block on a watcher that is mid-sleep."""
    memory_module.set_hindsight_base_url(None)
    monkeypatch.setattr(main_module, "_hindsight_reachable", lambda *a, **k: False)

    task = asyncio.create_task(
        main_module._await_hindsight(
            "http://memory.test:8888", every=30.0, give_up_after=600.0
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
