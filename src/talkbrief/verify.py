"""Verify stage: mechanically anchor every quote and measure hard-token recall.

This is the feature that separates a brief you can trust from a plausible one:

- Every quote the model wrote is located in the transcript (exact → ellipsis-aware →
  fuzzy ≥ 0.90). The fuzzy path additionally requires DIGIT-EXACT equality — fuzzy 0.90
  happily accepts "40 ms" vs "4 ms", and a fabricated number is the worst hallucination.
- A quote absent from speech is checked against slide OCR (that is a legitimate source:
  the slide often spells what the ASR mangled) and stamped source="slide".
- A short quote (< 4 words) passes only if it pins ≤ 3 locations — otherwise its
  timestamp would be a guess.
- Ungrounded quotes are STAMPED and rendered flagged, never silently dropped.
- Coverage: recall of hard tokens (numbers+units, versions, acronyms, flags,
  identifiers) from transcript to brief. The min-count filter applies to BOTH sides
  of the fraction — a one-sided filter once reported 6.3% for a 94.3% digest.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import unicodedata
from collections import Counter

from .config import RunConfig
from .rundir import RunDir
from .schemas import validate
from .util import read_json, write_json

log = logging.getLogger("talkbrief")

_FUZZY_RATIO_SPEECH = 0.90
_FUZZY_RATIO_SLIDE = 0.85  # the OCR is the noisy side
_SHORT_QUOTE_WORDS = 4
_SHORT_QUOTE_MAX_LOCATIONS = 3
_DIGITS_RE = re.compile(r"\d+(?:\.\d+)?")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def _norm_tokens(text: str) -> list[str]:
    return _normalize(text).split()


def _digits(text: str) -> list[str]:
    return sorted(_DIGITS_RE.findall(text))


class TranscriptIndex:
    def __init__(self, segments: list[dict]):
        self.tokens: list[str] = []
        self.times: list[float] = []
        for seg in segments:
            for tok in _norm_tokens(seg["text"]):
                self.tokens.append(tok)
                self.times.append(seg["start"])

    def find_exact(self, q: list[str], start: int = 0, max_hits: int = 8) -> list[int]:
        hits: list[int] = []
        n, m = len(self.tokens), len(q)
        if m == 0:
            return hits
        for i in range(start, n - m + 1):
            if self.tokens[i] == q[0] and self.tokens[i : i + m] == q:
                hits.append(i)
                if len(hits) >= max_hits:
                    break
        return hits

    def fuzzy_find(self, q: list[str], ratio: float) -> int | None:
        m = len(q)
        if m == 0 or len(self.tokens) < m:
            return None
        q_str, q_set = " ".join(q), set(q)
        best_i, best_r = None, ratio
        for i in range(0, len(self.tokens) - m + 1):
            window = self.tokens[i : i + m]
            if len(q_set.intersection(window)) < 0.5 * m:
                continue
            w_str = " ".join(window)
            r = difflib.SequenceMatcher(None, w_str, q_str).ratio()
            # digit-exact enforcement: a fuzzy match with different numbers is a lie
            if r >= best_r and _digits(w_str) == _digits(q_str):
                best_i, best_r = i, r
        return best_i


def _anchor_in_slides(quote_tokens: list[str], slides: list[dict]) -> float | None:
    q_str = " ".join(quote_tokens)
    for s in slides:
        st = _norm_tokens(s["ocr_text"])
        if len(st) < len(quote_tokens):
            continue
        for i in range(0, len(st) - len(quote_tokens) + 1):
            window = st[i : i + len(quote_tokens)]
            if window == quote_tokens:
                return s["first_seen_s"]
            if len(quote_tokens) >= _SHORT_QUOTE_WORDS:
                w_str = " ".join(window)
                if (
                    difflib.SequenceMatcher(None, w_str, q_str).ratio() >= _FUZZY_RATIO_SLIDE
                    and _digits(w_str) == _digits(q_str)
                ):
                    return s["first_seen_s"]
    return None


def anchor_quote(
    quote: str, index: TranscriptIndex, slides: list[dict]
) -> tuple[float | None, bool, str | None]:
    """Return (t_seconds, grounded, match_source)."""
    raw_fragments = [f for f in re.split(r"\s*(?:\.\.\.|…)\s*", quote.strip()) if _norm_tokens(f)]
    if len(raw_fragments) > 1:  # ellipsis quote: fragments must appear in order
        pos, first_t = 0, None
        for frag in raw_fragments:
            ft = _norm_tokens(frag)
            hits = index.find_exact(ft, start=pos, max_hits=1)
            if not hits:
                first_t = None
                break
            if first_t is None:
                first_t = index.times[hits[0]]
            pos = hits[0] + len(ft)
        if first_t is not None:
            return first_t, True, "speech"

    q = _norm_tokens(quote)
    if not q:
        return None, False, None
    hits = index.find_exact(q)
    if hits:
        if len(q) < _SHORT_QUOTE_WORDS and len(hits) > _SHORT_QUOTE_MAX_LOCATIONS:
            pass  # pins too many places — its timestamp would be a guess
        else:
            return index.times[hits[0]], True, "speech"
    if len(q) >= _SHORT_QUOTE_WORDS:
        i = index.fuzzy_find(q, _FUZZY_RATIO_SPEECH)
        if i is not None:
            return index.times[i], True, "speech"
    if (t := _anchor_in_slides(q, slides)) is not None:
        return t, True, "slide"
    return None, False, None


def _iter_quote_points(digest: dict):
    ov = digest["overview"]
    yield from ov.get("key_takeaways", [])
    yield from ov.get("glossary", [])
    yield from ov.get("chapters", [])
    yield from ov.get("numbers_and_names", [])
    for s in digest["slides"]:
        yield from s.get("speaker_points", [])
    for w in digest["windows"]:
        yield from w.get("points", [])


_HARD_TOKEN_PATTERNS = (
    re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|ms|s|sec|min|hours?|fps|gb|mb|kb|tb|k|b|x|×)\b", re.I),
    re.compile(r"\bv?\d+\.\d+(?:\.\d+)*\b"),
    re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b"),          # acronyms, from RAW (cased) text
    re.compile(r"--[a-z][\w-]+"),                    # CLI flags
    re.compile(r"\b\w+(?:[-_]\w+)+\b"),              # kebab/snake identifiers
)


def coverage_recall(transcript_raw: str, brief_text: str, min_count: int = 2) -> tuple[float | None, list[str]]:
    counts: Counter[str] = Counter()
    for pat in _HARD_TOKEN_PATTERNS:
        for m in pat.findall(transcript_raw):
            counts[m.strip()] += 1
    # the SAME min-count filter defines numerator and denominator
    eligible = {tok for tok, c in counts.items() if c >= min_count and len(tok) >= 2}
    if not eligible:
        return None, []
    brief_fold = brief_text.casefold()
    missing = [tok for tok in eligible if tok.casefold() not in brief_fold]
    missing.sort(key=lambda tok: -counts[tok])
    recall = 1.0 - len(missing) / len(eligible)
    return round(recall, 3), missing[:20]


def run_verify(rd: RunDir, cfg: RunConfig) -> dict:
    digest = read_json(rd.digest_path)
    transcript = read_json(rd.transcript_path)
    slides_doc = read_json(rd.slides_json)
    index = TranscriptIndex(transcript["segments"])
    slides = slides_doc["slides"]

    total = grounded = 0
    for point in _iter_quote_points(digest):
        quote = point.get("quote")
        if not quote:
            point.update({"t": None, "grounded": False, "match_source": None})
            continue
        total += 1
        t, ok, source = anchor_quote(quote, index, slides)
        grounded += int(ok)
        point.update({"t": t, "grounded": ok, "match_source": source})

    for chapter in digest["overview"].get("chapters", []):
        chapter["start_s"] = chapter.get("t")

    transcript_raw = " ".join(s["text"] for s in transcript["segments"])
    recall, missing = coverage_recall(transcript_raw, json.dumps(digest, ensure_ascii=False))

    digest["verification"] = {
        "quotes_total": total,
        "quotes_grounded": grounded,
        "token_recall": recall,
        "missing_tokens": missing,
    }
    validate("verified", digest)
    write_json(rd.verified_path, digest)
    log.info(
        "verify: %d/%d quotes grounded, token recall %s",
        grounded, total, f"{recall:.0%}" if recall is not None else "n/a",
    )
    if total and grounded / total < 0.8:
        log.warning("verify: more than 20%% of quotes failed to ground — inspect before trusting")
    return digest
