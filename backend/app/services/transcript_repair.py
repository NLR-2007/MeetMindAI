"""Repairing names that speech-to-text mangled.

Streaming STT guesses at anything outside its language model, so the words it
reliably destroys are exactly the ones that matter here: people's names and
product terms. "Samhita Mattam" comes back as "sanita matam", "Manasvi" as
"malas we", "Hindsight" as "insight". Those errors propagate — a commitment
is attributed to nobody because the spoken name no longer matches anyone.

This is a deliberately conservative, deterministic pass. It does not use a
model, because a model asked to "clean up" a transcript rewrites what people
said. It only replaces a token when:

  * a known name is a close match, and
  * the original is not an ordinary English word.

Everything else is left exactly as spoken, including genuine nonsense. A
transcript that reads oddly is honest; one that has been quietly rewritten is
not evidence any more, and evidence is what coaching and PromiseMirror are
built on.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Close enough to be the same name said badly, far enough not to collapse two
# different people into one. Tuned against real mangled output.
SINGLE_TOKEN_RATIO = 0.82
MULTI_TOKEN_RATIO = 0.78

# Never "correct" these into a name, however close they look.
COMMON_WORDS = {
    "a", "about", "actually", "all", "and", "any", "are", "as", "at", "back",
    "be", "because", "been", "before", "but", "by", "can", "come", "could",
    "date", "day", "do", "does", "done", "down", "even", "every", "first",
    "for", "from", "get", "give", "go", "good", "got", "group", "had", "has",
    "have", "he", "her", "here", "him", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "just", "know", "last", "like", "made", "make", "man",
    "many", "may", "me", "mean", "meet", "meeting", "more", "most", "much",
    "must", "my", "name", "need", "new", "next", "no", "not", "now", "of",
    "off", "okay", "on", "one", "only", "or", "other", "our", "out", "over",
    "own", "page", "part", "people", "put", "really", "right", "said", "same",
    "say", "see", "she", "should", "so", "some", "such", "take", "team",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "think", "this", "those", "time", "to", "told", "too", "two", "up", "us",
    "use", "very", "want", "was", "way", "we", "well", "were", "what", "when",
    "where", "which", "while", "who", "why", "will", "with", "work", "would",
    "yes", "yet", "you", "your",
}

# Terms this product's meetings are full of, which generic STT has never seen.
PRODUCT_TERMS = [
    "MeetMind",
    "PromiseMirror",
    "Hindsight",
    "Mark Up",
    "Recall",
    "Groq",
    "hackathon",
    "Microsoft",
    "transcript",
    "deadline",
    "commitment",
]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def build_vocabulary(
    participant_names: list[str], extra: list[str] | None = None
) -> list[str]:
    """Names worth protecting: whoever was in the room, plus product terms.

    Full names and their parts both go in, because people are addressed by
    either. Anything under three characters is dropped — too short to match
    on without colliding with ordinary words.
    """
    vocab: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        cleaned = term.strip()
        key = _norm(cleaned)
        if len(key) < 3 or key in seen:
            return
        seen.add(key)
        vocab.append(cleaned)

    for name in participant_names:
        add(name)
        for part in re.split(r"\s+", name.strip()):
            add(part)
    for term in (extra or []) + PRODUCT_TERMS:
        add(term)
    return vocab


def _best_match(candidate: str, vocab: list[str], threshold: float) -> str | None:
    key = _norm(candidate)
    if len(key) < 3 or key in COMMON_WORDS or candidate.lower() in COMMON_WORDS:
        return None

    best: tuple[float, str] | None = None
    for term in vocab:
        term_key = _norm(term)
        if not term_key:
            continue
        if term_key == key:
            # Already the right word. Return it only to fix capitalisation —
            # "hindsight" is the product, "Hindsight" is how it is written.
            return term if term != candidate else None
        score = _ratio(key, term_key)
        if score >= threshold and (best is None or score > best[0]):
            best = (score, term)
    return best[1] if best else None


def repair_line(line: str, vocab: list[str]) -> str:
    """Repair names within one line, leaving everything else untouched."""
    if not line.strip() or not vocab:
        return line

    # Two-word runs first: "sanita matam" is only recoverable as a pair.
    tokens = re.split(r"(\W+)", line)
    words = [(i, t) for i, t in enumerate(tokens) if t and t.isalpha()]

    i = 0
    while i < len(words) - 1:
        idx_a, word_a = words[i]
        idx_b, word_b = words[i + 1]
        # Only when they really are adjacent words.
        between = "".join(tokens[idx_a + 1 : idx_b])
        if between.strip() == "":
            pair = f"{word_a} {word_b}"
            match = _best_match(pair, vocab, MULTI_TOKEN_RATIO)
            if match and " " in match:
                tokens[idx_a] = match
                tokens[idx_b] = ""
                tokens[idx_a + 1 : idx_b] = [""] * (idx_b - idx_a - 1)
                i += 2
                continue
        i += 1

    for idx, token in [(i, t) for i, t in enumerate(tokens) if t and t.isalpha()]:
        match = _best_match(token, vocab, SINGLE_TOKEN_RATIO)
        if match and " " not in match:
            # Keep the original capitalisation style where it was capitalised.
            tokens[idx] = match
    return "".join(tokens)


def repair_transcript(text: str, vocab: list[str]) -> tuple[str, int]:
    """Repair a whole transcript. Returns the text and how many lines changed.

    Speaker prefixes come from the meeting platform, not from speech, so they
    are already correct and are left alone.
    """
    if not text or not vocab:
        return text, 0

    out: list[str] = []
    changed = 0
    for line in text.splitlines():
        speaker, sep, said = line.partition(":")
        if sep and said:
            fixed = repair_line(said, vocab)
            new_line = f"{speaker}:{fixed}"
        else:
            new_line = repair_line(line, vocab)
        if new_line != line:
            changed += 1
        out.append(new_line)
    return "\n".join(out), changed
