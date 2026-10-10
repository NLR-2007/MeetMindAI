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
CI_ONLY = {"ruff", "pytest", "pytest-asyncio", "respx"}
# Production needs none of the test tooling, and adds Google ID token
# verification for Firebase sign-in.
PROD_EXCLUDED = {"hindsight-all", "pytest", "pytest-asyncio", "respx"}
PROD_ONLY = {"google-auth"}


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


def test_prod_requirements_match_runtime_requirements() -> None:
    """The image that actually ships must not drift from the real pins.

    This file is what Cloud Run installs. Three dependencies - PyJWT,
    passlib and bcrypt - were previously only present as transitive
    dependencies of hindsight-all, which production excludes, so the image
    would have come up unable to hash a password or sign a token.
    """
    runtime = _pins(BACKEND / "requirements.txt")
    prod = _pins(BACKEND / "requirements-prod.txt")

    missing = set(runtime) - set(prod) - PROD_EXCLUDED
    assert not missing, (
        "In requirements.txt but not requirements-prod.txt: "
        + ", ".join(sorted(missing))
    )

    extra = set(prod) - set(runtime) - PROD_ONLY
    assert not extra, (
        "In requirements-prod.txt but not requirements.txt: "
        + ", ".join(sorted(extra))
    )

    mismatched = {
        name: (runtime[name], prod[name])
        for name in set(runtime) & set(prod)
        if runtime[name] != prod[name]
    }
    assert not mismatched, f"Version pins differ: {mismatched}"


def test_authentication_dependencies_are_declared_not_transitive() -> None:
    """The specific bug this guards against, named so it is not re-introduced.

    These arrived only via hindsight-all. Any install without it - CI and the
    production image both - had no `jwt`, `passlib` or `bcrypt`, so login
    failed at runtime while every local test passed.
    """
    for filename in (
        "requirements.txt",
        "requirements-ci.txt",
        "requirements-prod.txt",
    ):
        pins = _pins(BACKEND / filename)
        for package in ("pyjwt", "passlib", "bcrypt", "email-validator"):
            assert package in pins, f"{package} is not declared in {filename}"
