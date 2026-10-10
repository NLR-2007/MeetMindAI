"""The deployment config has to carry the headers the browser needs.

Google sign-in opens a popup, and Firebase reads ``window.closed`` on it to
tell "the user cancelled" from "still deciding". Under the browser's stricter
default that read is blocked and sign-in is abandoned mid-flow.

``next.config.ts`` declares the header that permits it, but every page in this
app is prerendered and served straight off Firebase Hosting's CDN -- the Next
server never runs for those requests, so its ``headers()`` never applies. The
header is only actually delivered if ``firebase.json`` declares it too. That
is easy to regress precisely because the Next config *looks* like it covers
it, so this test pins the config that really takes effect.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COOP = "Cross-Origin-Opener-Policy"
REQUIRED_VALUE = "same-origin-allow-popups"


def _hosting() -> dict:
    config = json.loads((REPO_ROOT / "firebase.json").read_text(encoding="utf-8"))
    return config["hosting"]


def test_firebase_hosting_sends_the_popup_header() -> None:
    headers = _hosting().get("headers", [])
    delivered = {
        (rule["source"], header["key"]): header["value"]
        for rule in headers
        for header in rule.get("headers", [])
    }
    assert ("**", COOP) in delivered, (
        "firebase.json must declare Cross-Origin-Opener-Policy for all paths. "
        "Declaring it only in next.config.ts does nothing for prerendered "
        f"pages. Got: {delivered}"
    )
    assert delivered[("**", COOP)] == REQUIRED_VALUE


def test_next_config_also_declares_it_for_the_server_rendered_path() -> None:
    """Static pages are covered above; this covers `next dev` and SSR."""
    source = (REPO_ROOT / "frontend" / "next.config.ts").read_text(encoding="utf-8")
    assert COOP in source
    assert REQUIRED_VALUE in source


def test_hosting_still_builds_the_frontend_from_source() -> None:
    """Guard against the headers edit accidentally dropping the framework wiring."""
    hosting = _hosting()
    assert hosting["source"] == "frontend"
    assert hosting["target"] == "meetmind"
    assert "frameworksBackend" in hosting
