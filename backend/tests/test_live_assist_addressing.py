"""Live Assist must not answer questions aimed at other people."""
from __future__ import annotations

import pytest

from app.routers.markup import _addressed_to, _looks_like_question

OWN = {"bunny", "bunny reddy"}


@pytest.mark.parametrize(
    "text",
    [
        "Bunny, when will the demo video be ready?",
        "What do you think Bunny?",
        "Can you confirm the date, bunny reddy?",
    ],
)
def test_named_questions_are_mine(text: str) -> None:
    assert _addressed_to(text, OWN) == "you"


@pytest.mark.parametrize(
    "text",
    [
        "Priya, when will the tests be ready?",
        "Akhil, can you confirm the budget?",
    ],
)
def test_questions_named_at_others_are_not_mine(text: str) -> None:
    assert _addressed_to(text, OWN) == "someone_else"


@pytest.mark.parametrize(
    "text",
    [
        "What is the hackathon deadline?",
        "How are we tracking against the plan?",
        "Is this the Microsoft hackathon or Google?",
    ],
)
def test_unaddressed_questions_go_to_the_room(text: str) -> None:
    """Nobody named means anyone may answer, so the assist still offers one."""
    assert _addressed_to(text, OWN) == "room"


def test_question_detection_still_works() -> None:
    assert _looks_like_question("What is the deadline?")
    assert _looks_like_question("Can you send the report")
    assert not _looks_like_question("The deadline is Friday")


# --- waiting for the speaker to finish -------------------------------------


def test_gap_helper_handles_bad_timestamps() -> None:
    from app.routers.markup import _seconds_between

    assert _seconds_between("2026-09-28T12:00:00Z", "2026-09-28T12:00:03Z") == 3.0
    assert _seconds_between(None, "2026-09-28T12:00:03Z") is None
    assert _seconds_between("not a date", "also not") is None


def test_unpunctuated_questions_wait_longer() -> None:
    """A sentence with no "?" may still be in progress, so allow more silence."""
    from app.routers.markup import (
        SILENCE_SECONDS,
        SILENCE_SECONDS_UNPUNCTUATED,
        SPEECH_JOIN_SECONDS,
    )

    assert SILENCE_SECONDS_UNPUNCTUATED > SILENCE_SECONDS
    # Chunks must be joinable across a gap longer than the short silence, or a
    # natural mid-sentence pause would split one question into two.
    assert SPEECH_JOIN_SECONDS >= SILENCE_SECONDS
