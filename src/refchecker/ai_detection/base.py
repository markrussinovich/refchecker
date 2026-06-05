"""Core types, honesty policy, and shared utilities for AI-text detection.

This module is the single source of truth for:

* the ``AIDetectionResult`` shape returned by every backend,
* the **banding / abstention thresholds** (conservative, specificity-first),
* the permanent honesty **disclaimer**, and
* text utilities (word counting, non-prose detection, windowing).

Design stance — repeatedly confirmed in the 2025-2026 literature: *no*
detector (open-source or commercial) is reliable on academic, non-native-
English, or heavily technical writing.  Every result this package produces is
therefore an **advisory signal for the author's own self-check**, never proof
of misconduct.  The thresholds below deliberately favour specificity (few
false "high") at the cost of recall, and the engine abstains aggressively.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ── Honesty policy constants ──────────────────────────────────────────────

#: Minimum prose word count below which NO detector is statistically
#: reliable (literature floor is 250-500 words; 300 is a defensible middle).
MIN_WORDS = 300

#: Calibrated-probability band cut points.  ``HIGH_THRESHOLD`` is a
#: conservative *heuristic* default, not a validated operating point — it is
#: centralized here so it can be tuned in one place once a validation set
#: exists.  Below ``MEDIUM_THRESHOLD`` → "low".
MEDIUM_THRESHOLD = 0.30
HIGH_THRESHOLD = 0.85

#: A unit whose non-prose fraction (math / code / numerals / citations)
#: exceeds this is not validated terrain for detectors → abstain.
NONPROSE_FRACTION_ABSTAIN = 0.40

#: Span windowing — never per-sentence (below the reliability floor).
SPAN_WINDOW_WORDS = 350
SPAN_OVERLAP = 0.5

#: Permanent, non-dismissable disclaimer shown on every result.
DISCLAIMER = (
    "AI-text detection is unreliable on academic, technical, and "
    "non-native-English writing, and on text that a human wrote and then "
    "polished with AI. This is an advisory signal for your own review — it "
    "is NOT evidence of misconduct and must never be used as the sole or "
    "primary basis for any accusation, grade, or decision."
)

#: Ordered bands (severity ascending among the "scored" ones).
BAND_UNAVAILABLE = "unavailable"
BAND_INCONCLUSIVE = "inconclusive"
BAND_LOW = "low"
BAND_MEDIUM = "medium"
BAND_HIGH = "high"

_BAND_RANK = {
    BAND_UNAVAILABLE: -2,
    BAND_INCONCLUSIVE: -1,
    BAND_LOW: 0,
    BAND_MEDIUM: 1,
    BAND_HIGH: 2,
}

#: Human-readable description of the current (heuristic) operating point.
OPERATING_POINT = (
    f"Heuristic thresholds (medium≥{MEDIUM_THRESHOLD:.2f}, "
    f"high≥{HIGH_THRESHOLD:.2f}); not calibrated against a validated "
    "academic false-positive target."
)


# ── Result types ──────────────────────────────────────────────────────────

@dataclass
class SuspectSpan:
    """An advisory passage that scored above the high threshold.

    Surfaced as a quoted excerpt with a reason — never as a per-sentence
    verdict.  ``confidence`` is qualitative ("low"/"medium"/"high").
    """

    quote: str
    reason: str = ""
    confidence: str = "medium"
    # The richest signal the desklib detector exposes: this window's own model
    # score (sigmoid prob in [0,1]). NOT a probability of guilt — surfaced only
    # so the user can see WHICH passages drove the band and by how much.
    model_score: Optional[float] = None
    # How many physically-adjacent overlapping windows also cleared the high
    # threshold (0, 1, or 2) — corroboration strength behind this passage.
    neighbour_agreement_count: Optional[int] = None
    # How the passage was validated ("multi_window_agreement").
    confidence_method: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "quote": self.quote,
            "reason": self.reason,
            "confidence": self.confidence,
            "model_score": self.model_score,
            "neighbour_agreement_count": self.neighbour_agreement_count,
            "confidence_method": self.confidence_method,
        }


@dataclass
class AIDetectionResult:
    """Document-level AI-likelihood result attached to a single article.

    ``overall_score`` is a model score in [0, 1] when available; it is
    deliberately NOT labelled a probability of guilt.  ``band`` is the
    primary user-facing signal.
    """

    band: str = BAND_UNAVAILABLE
    overall_score: Optional[float] = None
    confidence: str = "low"
    summary: str = ""
    spans: List[SuspectSpan] = field(default_factory=list)
    backend_used: Optional[str] = None
    model_version: Optional[str] = None
    operating_point: Optional[str] = None
    abstain_reason: Optional[str] = None
    # Human-readable detail for an abstention/failure (e.g. the underlying
    # exception when the local model fails to load). Surfaced to the UI so the
    # user can act on the REAL cause instead of a generic "failed to load".
    abstain_detail: Optional[str] = None
    word_count: int = 0
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> Dict:
        return {
            "band": self.band,
            "overall_score": self.overall_score,
            "confidence": self.confidence,
            "summary": self.summary,
            "spans": [s.to_dict() for s in self.spans],
            "backend_used": self.backend_used,
            "model_version": self.model_version,
            "operating_point": self.operating_point,
            "abstain_reason": self.abstain_reason,
            "abstain_detail": self.abstain_detail,
            "word_count": self.word_count,
            "disclaimer": self.disclaimer,
        }


# ── Convenience constructors ──────────────────────────────────────────────

def make_unavailable(reason: str, backend: Optional[str] = None,
                     word_count: int = 0,
                     detail: Optional[str] = None) -> AIDetectionResult:
    """No body text / missing deps / model-not-installed / timeout.

    ``detail`` carries the real underlying error (e.g. the load exception) so
    the UI can show WHY it failed rather than a generic message.
    """
    return AIDetectionResult(
        band=BAND_UNAVAILABLE,
        summary="AI-text detection could not run for this article.",
        backend_used=backend,
        abstain_reason=reason,
        abstain_detail=detail,
        word_count=word_count,
    )


def make_inconclusive(reason: str, backend: Optional[str] = None,
                      word_count: int = 0) -> AIDetectionResult:
    """Ran, but the input is below the reliability floor → abstain."""
    return AIDetectionResult(
        band=BAND_INCONCLUSIVE,
        summary="Not enough reliable signal to assess this article.",
        backend_used=backend,
        operating_point=OPERATING_POINT,
        abstain_reason=reason,
        word_count=word_count,
    )


# ── Text utilities ────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_TOKEN_RE = re.compile(r"\S+")


def count_words(text: str) -> int:
    """Count prose-like word tokens (letters only)."""
    if not text:
        return 0
    return len(_WORD_RE.findall(text))


def nonprose_fraction(text: str) -> float:
    """Estimate the fraction of tokens that are NOT prose words.

    A proxy for math / code / numeric tables / citation-list density.  Pure
    prose scores near 0; equation- or reference-list-heavy text scores high.
    """
    if not text:
        return 1.0
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return 1.0
    prose = _WORD_RE.findall(text)
    return max(0.0, 1.0 - (len(prose) / len(tokens)))


def should_abstain(text: str) -> Optional[str]:
    """Return an abstain reason, or None if the unit is assessable.

    Order matters: "too_short" before "technical_section" so the user sees
    the most actionable reason.
    """
    wc = count_words(text)
    if wc == 0:
        # No manuscript body at all (e.g. references read from a .bbl/.bib file
        # or a DOI lookup, so the full text was never extracted) — distinct from
        # a genuinely short body, so the UI can explain it honestly rather than
        # claim the text is "too short".
        return "no_body_text"
    if wc < MIN_WORDS:
        return "too_short"
    if nonprose_fraction(text) > NONPROSE_FRACTION_ABSTAIN:
        return "technical_section"
    return None


def iter_windows(text: str, window_words: int = SPAN_WINDOW_WORDS,
                 overlap: float = SPAN_OVERLAP) -> List[str]:
    """Split text into overlapping word windows (>= window_words each).

    Used for span scoring.  Never returns sub-``MIN_WORDS`` fragments: a
    trailing remainder shorter than the window is merged into the last
    window so every emitted window clears the reliability floor.
    """
    words = text.split()
    if len(words) <= window_words:
        return [text] if count_words(text) >= MIN_WORDS else []
    step = max(1, int(window_words * (1.0 - overlap)))
    windows: List[str] = []
    i = 0
    n = len(words)
    while i < n:
        chunk = words[i:i + window_words]
        if len(chunk) < window_words and windows:
            chunk_text = " ".join(chunk)
            # If the trailing chunk itself clears the reliability floor, emit it
            # as its own window — dropping it would silently exclude a large
            # prose region (up to ~19% of the body) from the score-driving mean.
            # (It overlaps the previous window by design, so physical-adjacency
            # for span corroboration still holds.)
            if count_words(chunk_text) >= MIN_WORDS:
                windows.append(chunk_text)
            # Otherwise it's a genuinely sub-floor tail: merge it into the
            # previous window if that stays within the encoder's token budget,
            # else drop it (too short to assess and would overflow the merge).
            elif len(windows[-1].split()) + len(chunk) <= int(window_words * 1.5):
                windows[-1] = windows[-1] + " " + chunk_text
            break
        windows.append(" ".join(chunk))
        if i + window_words >= n:
            break
        i += step
    return windows


def truncate_quote(text: str, max_chars: int = 400) -> str:
    """Trim a window down to a readable excerpt for the UI."""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


# ── Banding helpers ───────────────────────────────────────────────────────

def band_from_probability(p: float) -> str:
    """Map a calibrated score in [0, 1] to a conservative band."""
    if p >= HIGH_THRESHOLD:
        return BAND_HIGH
    if p >= MEDIUM_THRESHOLD:
        return BAND_MEDIUM
    return BAND_LOW


def band_rank(band: str) -> int:
    return _BAND_RANK.get(band, -1)


def combine_bands_and(bands: List[str]) -> str:
    """Intersection/AND combination of scoring backends.

    "high" only if *every* scoring backend independently reaches "high";
    any disagreement demotes.  This deliberately raises the bar for
    accusation as detectors are added — the only safe direction.  Abstain
    states dominate (if any backend abstained we are not confident).
    """
    scored = [b for b in bands if b in (BAND_LOW, BAND_MEDIUM, BAND_HIGH)]
    if not scored:
        # No backend produced a score → propagate the least-severe abstain.
        if BAND_INCONCLUSIVE in bands:
            return BAND_INCONCLUSIVE
        return BAND_UNAVAILABLE
    # Abstain states dominate: if ANY backend abstained we are not confident,
    # so the combination must not assert a band — demote to inconclusive. Only
    # when every backend scored do we take the least-severe scored band.
    if any(b not in (BAND_LOW, BAND_MEDIUM, BAND_HIGH) for b in bands):
        return BAND_INCONCLUSIVE
    return min(scored, key=band_rank)


def clamp_not_above(primary: str, secondary: str) -> str:
    """Return ``secondary`` capped so it never exceeds ``primary``.

    Used to enforce the rule that an explanation/LLM backend may only
    *lower* the calibrated detector's severity, never raise it.
    """
    if band_rank(secondary) > band_rank(primary):
        return primary
    return secondary


# ── Backend contract ──────────────────────────────────────────────────────

class DetectionBackend(ABC):
    """A pluggable AI-text-detection engine.

    Implementations MUST be safe to instantiate even when their underlying
    dependency / model / key is missing — ``available`` reports readiness and
    ``detect`` returns an "unavailable" result rather than raising.
    """

    #: Stable identifier used in settings and persisted results.
    name: str = "base"

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether this backend can actually run right now."""

    @abstractmethod
    def detect(self, text: str, *, title: Optional[str] = None) -> AIDetectionResult:
        """Analyze the manuscript body ``text`` and return a result.

        Implementations should apply :func:`should_abstain` before scoring
        and must populate ``disclaimer`` / ``operating_point`` honestly.
        """


# ── Body-text cleanup (feed the detector authored prose, not boilerplate) ──

# Start of the reference list / bibliography — everything after is citations.
_REFS_HEADER_RE = re.compile(
    r"(?im)^[^\S\n]*(?:references|bibliography|works\s+cited|literature\s+cited|"
    r"reference\s+list)[^\S\n]*$"
)

# Journal front-matter / boilerplate the detector must NOT score: open-access /
# Creative-Commons license blurbs, copyright lines, correspondence, affiliations,
# DOIs, emails, received/accepted dates, keyword lines. These are templated and
# score as "AI-like" but are not authored manuscript prose.
_BOILERPLATE_LINE_RE = re.compile(
    r"(?im)^(?:"
    r".*(?:creative\s+commons|open\s+access|this\s+article\s+is\s+licensed|"
    r"licensed\s+under|creativecommons\.org|all\s+rights\s+reserved|"
    r"the\s+author\(s\)\s*\d{4}|©|correspondence|full\s+list\s+of\s+author|"
    r"received\s*:.*accepted|https?://doi\.org|doi\.org/10\.|keywords).*"
    r"|.*[\w.+-]+@[\w-]+\.[\w.-]+.*"
    r")$"
)


def strip_nonbody(text: str) -> str:
    """Remove journal boilerplate so the AI-detector scores authored prose, not
    templated front-matter / references.

    Drops, in order: the reference list, the title/author/affiliation/license
    front-matter (by starting at the Abstract or Introduction), then residual
    license / copyright / correspondence / email / DOI / keyword lines. Every
    step is conservative — it only applies when >= MIN_WORDS of body survives,
    so a short or unusually-formatted paper is never gutted.
    """
    if not text:
        return text or ""
    t = text

    # 1) Cut the reference list tail.
    m = None
    for m in _REFS_HEADER_RE.finditer(t):
        pass  # keep the LAST heading match (avoids "references" inside the intro)
    if m and count_words(t[: m.start()]) >= MIN_WORDS:
        t = t[: m.start()]

    # 2) Start at the Abstract / Introduction to drop the leading front matter
    #    (title, authors, affiliations, open-access license, correspondence).
    for kw in (r"\bAbstract\b", r"\bIntroduction\b"):
        am = re.search(kw, t, re.IGNORECASE)
        if am and am.start() < len(t) * 0.4 and count_words(t[am.start():]) >= MIN_WORDS:
            t = t[am.start():]
            break

    # 3) Scrub residual boilerplate lines wherever they sit in the body.
    scrubbed = _BOILERPLATE_LINE_RE.sub("", t)
    if count_words(scrubbed) >= MIN_WORDS:
        t = scrubbed

    return re.sub(r"[^\S\n]{2,}", " ", re.sub(r"\n{2,}", "\n", t)).strip()


def prepared_text(text: str) -> Tuple[str, int]:
    """Clean boilerplate, normalize whitespace, return ``(clean_text, word_count)``."""
    clean = strip_nonbody((text or "").strip())
    return clean, count_words(clean)


# ── Usage / cost tracking ─────────────────────────────────────────────────

#: Rough USD price per 1,000 words for the paid external detection services
#: (public 2026 pricing; used only to surface an estimated spend in the meter).
API_PRICE_PER_1K_WORDS = {
    "pangram": 0.05,
    "gptzero": 0.015,
}


def estimate_api_cost(service: str, words: int) -> float:
    """Estimate the USD cost of an external-API detection call."""
    rate = API_PRICE_PER_1K_WORDS.get((service or "").lower(), 0.0)
    return round((max(0, words) / 1000.0) * rate, 6)


def record_detection_usage(
    check_id,
    model: str,
    *,
    flow: str = "ai_detection",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: Optional[float] = None,
) -> None:
    """Attribute an AI-detection unit of work to the per-check usage meter.

    Local/API backends have no LLM tokens, so they pass the processed word
    count as ``input_tokens`` (the meter drops zero-token records) and an
    explicit ``cost_usd`` ($0 for the local model). Best-effort: a tracking
    failure never affects detection. Mirrors how the LLM extraction path
    records into ``refchecker.llm.usage_tracker``.

    No-op when ``check_id`` is None — there is no per-check context to attribute
    to (e.g. the free graph abstract path), and we must not pollute the shared
    "default" usage bucket.
    """
    if check_id is None:
        return
    try:
        from refchecker.llm import usage_tracker
        usage_tracker.record(
            check_id=check_id,
            model=model,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            flow=flow,
            cost_usd=cost_usd,
        )
    except Exception:  # noqa: BLE001
        pass
