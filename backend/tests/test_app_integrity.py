"""Whole-app checks that catch mistakes no single feature test would.

`from __future__ import annotations` makes every annotation a string, so a
missing import in a type hint stays invisible until something resolves it.
Two of those shipped undetected (`Any` in the delete endpoint, `User` in the
coaching service). These tests resolve the hints on purpose so the next one
fails here instead of in production.
"""
from __future__ import annotations

import inspect
import typing

import pytest
from fastapi.routing import APIRoute

from app.main import app


def _routes(routes: list | None = None) -> list[APIRoute]:
    """Every endpoint, including those behind include_router().

    FastAPI wraps an included router rather than flattening its routes into
    `app.routes`, so a plain isinstance filter sees only the two handlers
    declared on `app` itself and would pass while testing almost nothing.
    """
    found: list[APIRoute] = []
    for route in app.routes if routes is None else routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):
            found.extend(_routes(route.original_router.routes))
    return found


def test_route_discovery_is_not_vacuous() -> None:
    """Guard the guard: if discovery breaks, the checks below pass emptily."""
    assert len(_routes()) > 40


@pytest.mark.parametrize("route", _routes(), ids=lambda r: f"{r.path}")
def test_route_type_hints_resolve(route: APIRoute) -> None:
    """Every endpoint's annotations must name things that actually exist."""
    typing.get_type_hints(route.endpoint)


def test_service_and_router_function_hints_resolve() -> None:
    """The same guarantee for the modules behind the endpoints."""
    import importlib
    import pkgutil

    import app as app_package

    failures: list[str] = []
    for module_info in pkgutil.walk_packages(
        app_package.__path__, prefix="app."
    ):
        module = importlib.import_module(module_info.name)
        for name, obj in vars(module).items():
            if not inspect.isfunction(obj) or obj.__module__ != module.__name__:
                continue
            try:
                typing.get_type_hints(obj)
            except Exception as exc:
                failures.append(f"{module_info.name}.{name}: {exc}")

    assert not failures, "Unresolvable type hints:\n" + "\n".join(failures)


def test_no_duplicate_route_paths() -> None:
    """Two handlers on one method+path means one of them is unreachable."""
    seen: dict[tuple[str, str], str] = {}
    clashes: list[str] = []
    for route in _routes():
        for method in route.methods or set():
            key = (method, route.path)
            if key in seen:
                clashes.append(f"{method} {route.path}: {seen[key]} and {route.name}")
            seen[key] = route.name
    assert not clashes, "Duplicate routes:\n" + "\n".join(clashes)


# The manager rollup that was deliberately removed. /teams is a different
# thing entirely: it shares one bot between colleagues, and grants no
# visibility into anyone's promises, coaching or progress.
MANAGER_ROLLUP_PATHS = {
    "/team/overview",
    "/team/commitments",
    "/team/deadlines",
    "/team/findings",
    "/team/projects",
}


def test_removed_manager_dashboard_is_really_gone() -> None:
    """The manager rollup was removed; nothing should quietly re-register it."""
    paths = {r.path for r in _routes()}
    assert not (paths & MANAGER_ROLLUP_PATHS)


def test_teams_grant_no_rollup_endpoints() -> None:
    """Teams must not become the manager dashboard by another name.

    Everything under /teams is about membership and invites. The moment one
    of them starts serving other people's commitments or progress, the
    distinction this feature rests on has been lost.
    """
    team_paths = sorted(r.path for r in _routes() if r.path.startswith("/teams"))
    assert team_paths, "the teams feature should register routes"
    forbidden = ("commitment", "progress", "finding", "deadline", "coach")
    leaking = [p for p in team_paths if any(word in p for word in forbidden)]
    assert not leaking, f"/teams must not expose other people's work: {leaking}"
