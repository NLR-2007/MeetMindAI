"""The CI dependency list must not drift from the real one.

requirements-ci.txt exists only to skip hindsight-all's model stack. If a pin
moves in requirements.txt and not here, CI silently starts testing different
versions from the ones the app ships with, which is worse than no CI.
"""
from __future__ import annotations

import pathlib

BACKEND = pathlib.Path(__file__).resolve().parent.parent

# Deliberately absent from CI, with the reason recorded in requirements-ci.txt.
CI_EXCLUDED = {"hindsight-all"}
# Present only in CI, never needed at runtime.
CI_ONLY = {"ruff"}


def _pins(path: pathlib.Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue
        name, version = line.split("==", 1)
        # Normalise "uvicorn[standard]" to "uvicorn" for comparison.
        pins[name.split("[", 1)[0].strip().lower()] = version.strip()
    return pins


def test_ci_requirements_match_runtime_requirements() -> None:
    runtime = _pins(BACKEND / "requirements.txt")
    ci = _pins(BACKEND / "requirements-ci.txt")

    assert runtime, "requirements.txt parsed as empty; the parser is wrong"

    missing = set(runtime) - set(ci) - CI_EXCLUDED
    assert not missing, (
        "In requirements.txt but not requirements-ci.txt: "
        + ", ".join(sorted(missing))
    )

    extra = set(ci) - set(runtime) - CI_ONLY
    assert not extra, (
        "In requirements-ci.txt but not requirements.txt: " + ", ".join(sorted(extra))
    )

    mismatched = {
        name: (runtime[name], ci[name])
        for name in set(runtime) & set(ci)
        if runtime[name] != ci[name]
    }
    assert not mismatched, f"Version pins differ between the two files: {mismatched}"


def test_excluded_dependency_is_still_a_real_runtime_pin() -> None:
    """If hindsight-all is ever renamed, this exclusion must be revisited."""
    runtime = _pins(BACKEND / "requirements.txt")
    for name in CI_EXCLUDED:
        assert name in runtime, (
            f"{name} is excluded from CI but no longer appears in "
            "requirements.txt; update CI_EXCLUDED."
        )
