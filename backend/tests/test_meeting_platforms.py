"""Link shapes MeetMind accepts, and the ones it must keep rejecting.

The platform name returned here is handed straight to Recall, so a new URL
spelling must map onto an identifier Recall already knows rather than
inventing one.
"""
from __future__ import annotations

import pytest

from app.schemas import MEETING_URL_PATTERNS, detect_platform

# Recall's own platform identifiers. Anything detect_platform returns must be
# in this set, or the bot request is rejected upstream.
RECALL_PLATFORMS = {"google_meet", "zoom", "teams", "webex", "slack", "goto"}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://meet.google.com/abc-defg-hij", "google_meet"),
        ("https://meet.google.com/abc-defg-hij?authuser=1", "google_meet"),
        ("https://meet.google.com/lookup/abc123xyz", "google_meet"),
        ("https://zoom.us/j/1234567890", "zoom"),
        ("https://acme.zoom.us/j/1234567890?pwd=xyz", "zoom"),
        ("https://acme.zoom.us/w/9876543210", "zoom"),
        ("https://acme.zoom.us/my/lokesh.reddy", "zoom"),
        ("https://teams.microsoft.com/l/meetup-join/19%3ameeting", "teams"),
        ("https://teams.live.com/meet/9876543", "teams"),
        ("https://acme.webex.com/meet/lokesh", "webex"),
        ("https://app.slack.com/huddle/T123/C456", "slack"),
        ("https://gotomeet.me/lokesh", "goto"),
    ],
)
def test_supported_links_are_recognised(url: str, expected: str) -> None:
    assert detect_platform(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/xyz",
        "https://meet.google.com/",
        "not a url at all",
        "http://meet.google.com/abc-defg-hij",  # plain http is not a Meet link
    ],
)
def test_unsupported_links_are_rejected(url: str) -> None:
    assert detect_platform(url) is None


def test_every_platform_name_is_one_recall_knows() -> None:
    """A new URL spelling must not invent a platform identifier.

    Adding a "zoom_personal" key would have sent that string to Recall, which
    only understands its own names.
    """
    assert set(MEETING_URL_PATTERNS) <= RECALL_PLATFORMS


def test_all_zoom_spellings_report_the_same_platform() -> None:
    for url in (
        "https://zoom.us/j/1234567890",
        "https://acme.zoom.us/my/lokesh.reddy",
    ):
        assert detect_platform(url) == "zoom"
