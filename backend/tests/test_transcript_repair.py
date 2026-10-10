"""Name repair, tested against real mangled output from a live meeting.

Every "mangled" string below came out of the actual speech-to-text on a real
call, not from imagination. The job is to recover names and product terms
without rewriting what people said.
"""
from __future__ import annotations

import pytest

from app.services.transcript_repair import (
    build_vocabulary,
    repair_line,
    repair_transcript,
)

PARTICIPANTS = ["Samhita Mattam", "Nimma Lokesh Reddy", "Manasvi Param"]
VOCAB = build_vocabulary(PARTICIPANTS)


# --- errors that actually happened, and are recoverable -------------------


@pytest.mark.parametrize(
    ("mangled", "expected"),
    [
        ("sanita matam", "Samhita Mattam"),
        ("samita", "Samhita"),
        ("manasri", "Manasvi"),
        ("manasvina message", "Manasvi message"),
        ("nadi sanita matam at the rate", "nadi Samhita Mattam at the rate"),
    ],
)
def test_mangled_names_are_recovered(mangled: str, expected: str) -> None:
    assert repair_line(mangled, VOCAB) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("rather than hindsight", "rather than Hindsight"),
        ("microsoft hyderabad campus", "Microsoft hyderabad campus"),
        ("samhita kura", "Samhita kura"),
    ],
)
def test_known_terms_get_their_proper_spelling(spoken: str, expected: str) -> None:
    """STT lowercases everything; these are names, and names have a spelling."""
    assert repair_line(spoken, VOCAB) == expected


# --- what it must NOT do --------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "i have to leave by 10 o clock so",
        "what is this childish behavior location come on",
        "so there is no group promise board",
        "okay but original value",
        "yes",
        "the next meeting will be tomorrow and email sent calendar access",
    ],
)
def test_ordinary_speech_is_left_exactly_as_spoken(line: str) -> None:
    """A transcript quietly rewritten is no longer evidence.

    Coaching quotes it back and PromiseMirror cites it, so anything this pass
    is not sure about has to survive untouched.
    """
    assert repair_line(line, VOCAB) == line


@pytest.mark.parametrize("line", ["at a trophy blocker voice rock", "antenna", "ail sepika"])
def test_unrecoverable_nonsense_is_preserved_not_invented(line: str) -> None:
    """Where the audio was lost, it stays lost.

    Guessing a plausible sentence here would be the worst possible failure:
    a confident, wrong record of what somebody said.
    """
    assert repair_line(line, VOCAB) == line


def test_a_name_is_never_collapsed_into_a_different_person() -> None:
    """Two real people who sound alike must not become one."""
    vocab = build_vocabulary(["Manasvi Param", "Manisha Patel"])
    assert repair_line("Manasvi", vocab) == "Manasvi"
    assert repair_line("Manisha", vocab) == "Manisha"


def test_short_tokens_are_ignored() -> None:
    """Two letters cannot be matched on without hitting ordinary words."""
    vocab = build_vocabulary(["Jo Li"])
    assert repair_line("so we go to it", vocab) == "so we go to it"


# --- whole transcripts ----------------------------------------------------


def test_speaker_labels_are_never_touched() -> None:
    """Those come from the meeting platform, not from speech: already right."""
    text = "Samhita Mattam: nadi sanita matam at the rate gmailcom"
    fixed, changed = repair_transcript(text, VOCAB)
    assert fixed.startswith("Samhita Mattam:")
    assert "Samhita Mattam at the rate" in fixed
    assert changed == 1


def test_repair_reports_how_much_it_changed() -> None:
    text = "\n".join(
        [
            "Samhita Mattam: samita here",
            "Manasvi Param: okay but original value",
            "Nimma Lokesh Reddy: manasri can you check",
        ]
    )
    fixed, changed = repair_transcript(text, VOCAB)
    # Two lines had a recoverable name; the middle one is ordinary speech.
    assert changed == 2
    assert "okay but original value" in fixed


def test_no_vocabulary_means_no_changes() -> None:
    text = "sanita matam said something"
    assert repair_transcript(text, [])[0] == text


def test_empty_transcript_is_handled() -> None:
    assert repair_transcript("", VOCAB) == ("", 0)


def test_vocabulary_includes_name_parts_and_products() -> None:
    vocab = [v.lower() for v in build_vocabulary(["Nimma Lokesh Reddy"])]
    assert "nimma lokesh reddy" in vocab
    assert "lokesh" in vocab
    assert "hindsight" in vocab
