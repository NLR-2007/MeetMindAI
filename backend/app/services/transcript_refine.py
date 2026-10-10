"""Whisper's words, Recall's speakers.

Streaming speech-to-text is built for latency, and on code-switched speech —
English mixed with another language, as in most of the world — it renders the
non-English stretches as English-sounding nonsense. "At a trophy blocker voice
rock" is not a transcription failure anyone can post-process their way out of;
the words were never recognised.

Whisper reads that speech far better, but it has no idea who is talking, and
speaker attribution is load-bearing here: coaching is scoped to your own
lines and refuses to review anyone else's. Throwing Recall's utterances away
would break the thing that makes this product trustworthy.

So neither is discarded. Whisper's segments carry timestamps, and Recall's
utterances carry timestamps and a speaker. Overlapping them in time gives
each utterance better words while keeping the person who said them.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# A Whisper segment is credited to the utterance it overlaps most. Below this
# share of the segment, the overlap is incidental and it is left alone.
MIN_OVERLAP = 0.35


def _utterance_span(utterance: dict[str, Any]) -> tuple[float, float] | None:
    """Start and end of an utterance, in seconds relative to the recording."""
    words = utterance.get("words") or []
    starts: list[float] = []
    ends: list[float] = []
    for word in words:
        stamp = word.get("start_timestamp") or {}
        relative = stamp.get("relative")
        if relative is None:
            continue
        try:
            value = float(relative)
        except (TypeError, ValueError):
            continue
        starts.append(value)
        end_stamp = word.get("end_timestamp") or {}
        end_rel = end_stamp.get("relative")
        try:
            ends.append(float(end_rel) if end_rel is not None else value)
        except (TypeError, ValueError):
            ends.append(value)
    if not starts:
        return None
    return min(starts), max(ends or starts)


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def align(
    utterances: list[dict[str, Any]], segments: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Give each utterance the Whisper text that overlaps it in time.

    Returns new utterances and how many were rewritten. An utterance with no
    usable timestamps, or with nothing overlapping it, keeps its original
    words: a gap in Whisper's output must never blank out something that was
    definitely said.
    """
    if not utterances or not segments:
        return utterances, 0

    spans: list[tuple[int, tuple[float, float]]] = []
    for index, utterance in enumerate(utterances):
        span = _utterance_span(utterance)
        if span is not None:
            spans.append((index, span))
    if not spans:
        logger.info("No usable timestamps on the utterances; leaving text as-is")
        return utterances, 0

    # Each segment goes to whichever utterance it sits inside the most.
    claimed: dict[int, list[str]] = {}
    for segment in segments:
        seg_span = (segment["start"], segment["end"])
        seg_length = max(seg_span[1] - seg_span[0], 0.01)
        best: tuple[float, int] | None = None
        for index, span in spans:
            share = _overlap(seg_span, span) / seg_length
            if share >= MIN_OVERLAP and (best is None or share > best[0]):
                best = (share, index)
        if best is not None:
            claimed.setdefault(best[1], []).append(segment["text"])

    refined: list[dict[str, Any]] = []
    rewritten = 0
    for index, utterance in enumerate(utterances):
        texts = claimed.get(index)
        if not texts:
            refined.append(utterance)
            continue
        better = " ".join(texts).strip()
        if not better:
            refined.append(utterance)
            continue
        copy = dict(utterance)
        # One synthetic word carrying the whole refined phrase, keeping the
        # original start time so ordering and Live Assist stitching still work.
        first = (utterance.get("words") or [{}])[0]
        copy["words"] = [
            {
                "text": better,
                "start_timestamp": first.get("start_timestamp"),
                "end_timestamp": first.get("end_timestamp"),
            }
        ]
        copy["refined_by"] = "whisper"
        refined.append(copy)
        rewritten += 1

    return refined, rewritten


def whisper_prompt(participant_names: list[str], extra_terms: list[str]) -> str:
    """Seed Whisper with the names it would otherwise invent.

    Whisper accepts a short prompt as a spelling hint. Feeding it the people
    in the room and the product's own vocabulary is the cheapest accuracy win
    available, and it costs nothing per minute.
    """
    terms = [t.strip() for t in [*participant_names, *extra_terms] if t and t.strip()]
    seen: list[str] = []
    for term in terms:
        if term not in seen:
            seen.append(term)
    if not seen:
        return ""
    return (
        "The following names and terms appear in this recording: "
        + ", ".join(seen)
        + "."
    )
