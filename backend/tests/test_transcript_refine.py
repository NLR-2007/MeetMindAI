"""Whisper's words onto Recall's speakers.

Streaming STT renders code-switched speech as English-sounding nonsense;
Whisper reads it properly but does not know who spoke. Aligning the two by
timestamp is what gives better text without losing attribution — and
attribution is load-bearing, because coaching refuses to review anyone's
words but your own.
"""
from __future__ import annotations

from app.services.transcript_refine import align, whisper_prompt
from app.services.transcripts import parse_transcript


def _utt(name: str, text: str, start: float, end: float) -> dict:
    return {
        "participant": {"id": abs(hash(name)) % 1000, "name": name},
        "words": [
            {
                "text": text,
                "start_timestamp": {"relative": start},
                "end_timestamp": {"relative": end},
            }
        ],
    }


def _seg(text: str, start: float, end: float) -> dict:
    return {"text": text, "start": start, "end": end}


def test_whisper_text_replaces_the_mangled_words_but_keeps_the_speaker() -> None:
    utterances = [
        _utt("Nimma Lokesh Reddy", "at a trophy blocker voice rock", 0.0, 4.0),
        _utt("Samhita Mattam", "which building one okay", 4.5, 7.0),
    ]
    segments = [
        _seg("Actually the audio is blocking my voice.", 0.1, 3.9),
        _seg("Which building? Building one, okay.", 4.6, 6.9),
    ]

    refined, rewritten = align(utterances, segments)
    assert rewritten == 2

    parsed = parse_transcript(refined)
    assert "Nimma Lokesh Reddy: Actually the audio is blocking my voice." in parsed.plain_text
    assert "Samhita Mattam: Which building?" in parsed.plain_text
    # The speaker is still the platform's, not a guess.
    assert {p.name for p in parsed.participants} == {
        "Nimma Lokesh Reddy",
        "Samhita Mattam",
    }


def test_a_segment_goes_to_whoever_it_overlaps_most() -> None:
    utterances = [
        _utt("A", "first", 0.0, 5.0),
        _utt("B", "second", 5.0, 10.0),
    ]
    # Mostly inside B's turn, with a little spill into A's.
    segments = [_seg("belongs to B", 4.6, 9.0)]

    refined, rewritten = align(utterances, segments)
    assert rewritten == 1
    assert refined[0]["words"][0]["text"] == "first"
    assert refined[1]["words"][0]["text"] == "belongs to B"


def test_an_utterance_with_no_whisper_coverage_keeps_its_words() -> None:
    """A gap in Whisper must never blank out something definitely said."""
    utterances = [
        _utt("A", "definitely said this", 0.0, 2.0),
        _utt("B", "and this", 50.0, 52.0),
    ]
    segments = [_seg("only covers the start", 0.0, 2.0)]

    refined, rewritten = align(utterances, segments)
    assert rewritten == 1
    assert refined[1]["words"][0]["text"] == "and this"


def test_no_segments_changes_nothing() -> None:
    utterances = [_utt("A", "original", 0.0, 1.0)]
    assert align(utterances, []) == (utterances, 0)


def test_no_utterances_changes_nothing() -> None:
    assert align([], [_seg("anything", 0.0, 1.0)]) == ([], 0)


def test_utterances_without_timestamps_are_left_alone() -> None:
    """Without timestamps there is nothing to align on, so nothing is risked."""
    utterances = [{"participant": {"name": "A"}, "words": [{"text": "no stamps"}]}]
    refined, rewritten = align(utterances, [_seg("better text", 0.0, 5.0)])
    assert rewritten == 0
    assert refined[0]["words"][0]["text"] == "no stamps"


def test_barely_touching_segments_are_not_credited() -> None:
    """A sliver of overlap is coincidence, not the same sentence."""
    utterances = [_utt("A", "keep me", 0.0, 10.0)]
    segments = [_seg("drive-by", 9.8, 20.0)]
    refined, rewritten = align(utterances, segments)
    assert rewritten == 0
    assert refined[0]["words"][0]["text"] == "keep me"


def test_refined_utterances_are_marked_as_such() -> None:
    """Provenance matters: the record should say the text was re-read."""
    utterances = [_utt("A", "mangled", 0.0, 2.0)]
    refined, _ = align(utterances, [_seg("clear", 0.0, 2.0)])
    assert refined[0]["refined_by"] == "whisper"


def test_the_prompt_seeds_whisper_with_names_it_would_otherwise_invent() -> None:
    prompt = whisper_prompt(
        ["Samhita Mattam", "Manasvi Param"], ["Hindsight", "MeetMind"]
    )
    assert "Samhita Mattam" in prompt
    assert "Hindsight" in prompt


def test_the_prompt_is_empty_when_there_is_nothing_to_seed() -> None:
    assert whisper_prompt([], []) == ""


def test_the_prompt_does_not_repeat_itself() -> None:
    prompt = whisper_prompt(["Hindsight"], ["Hindsight"])
    assert prompt.count("Hindsight") == 1
