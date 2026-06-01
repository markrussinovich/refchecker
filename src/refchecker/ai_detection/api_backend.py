"""External-API detection backend (Pangram / GPTZero).

Opt-in only: it sends the (possibly unpublished) manuscript body to a third
party, so it requires BOTH an API key AND an explicit consent flag.  Adapters
are intentionally defensive about response shapes and degrade to "unavailable"
on any error — a flaky external service must never break the citation check.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .base import (
    AIDetectionResult,
    DetectionBackend,
    SuspectSpan,
    BAND_MEDIUM,
    HIGH_THRESHOLD,
    OPERATING_POINT,
    DISCLAIMER,
    band_from_probability,
    band_rank,
    count_words,
    estimate_api_cost,
    make_inconclusive,
    make_unavailable,
    prepared_text,
    record_detection_usage,
    should_abstain,
    truncate_quote,
)

logger = logging.getLogger(__name__)

_PANGRAM_URL = "https://text.api.pangram.com/"
_GPTZERO_URL = "https://api.gptzero.me/v2/predict/text"
_TIMEOUT = 60
_MAX_CHARS = 60_000
# Minimum words for an externally-supplied span to be surfaced. The package's
# stance is "never per-sentence" (single sentences fall below the reliability
# floor); this filters out one-liner highlights from sentence-level APIs.
_MIN_SPAN_WORDS = 25


class ApiBackend(DetectionBackend):
    name = "api"

    def __init__(self, service: str = "pangram", api_key: Optional[str] = None,
                 consent: bool = False, check_id=None):
        self.service = (service or "pangram").lower()
        self.api_key = api_key
        self.consent = bool(consent)
        self.check_id = check_id
        self.model_version = f"api:{self.service}"

    @property
    def available(self) -> bool:
        return bool(self.api_key) and self.consent

    def detect(self, text: str, *, title: Optional[str] = None) -> AIDetectionResult:
        body, wc = prepared_text(text)
        if not self.api_key:
            return make_unavailable("api_key_missing", self.name, wc)
        if not self.consent:
            return make_unavailable("consent_required", self.name, wc)
        reason = should_abstain(body)
        if reason:
            return make_inconclusive(reason, self.name, wc)

        try:
            import requests
        except Exception:  # noqa: BLE001
            return make_unavailable("requests_missing", self.name, wc)

        sent_words = count_words(body[:_MAX_CHARS])
        try:
            if self.service == "gptzero":
                score, spans = self._gptzero(requests, body[:_MAX_CHARS])
            else:
                score, spans = self._pangram(requests, body[:_MAX_CHARS])
        except Exception as exc:  # noqa: BLE001
            logger.warning("API detection (%s) failed: %s", self.service, exc)
            return make_unavailable("api_call_failed", self.name, wc)

        # The request billed regardless of the score parsed: record the words
        # sent and the estimated USD cost for the usage meter.
        record_detection_usage(
            self.check_id, self.model_version,
            input_tokens=sent_words,
            cost_usd=estimate_api_cost(self.service, sent_words),
        )

        if score is None:
            return make_inconclusive("insufficient_signal", self.name, wc)

        band = band_from_probability(score)
        if band_rank(band) < band_rank(BAND_MEDIUM):
            spans = []
        return AIDetectionResult(
            band=band,
            overall_score=round(float(score), 3),
            confidence="medium",
            summary=f"{self.service} score {score:.2f}.",
            spans=spans[:8],
            backend_used=self.name,
            model_version=self.model_version,
            operating_point=OPERATING_POINT,
            word_count=wc,
            disclaimer=DISCLAIMER,
        )

    # -- service adapters ---------------------------------------------------

    def _pangram(self, requests, body: str):
        resp = requests.post(
            _PANGRAM_URL, headers={"x-api-key": self.api_key},
            json={"text": body}, timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        score = _coerce_score(
            data.get("ai_likelihood")
            if data.get("ai_likelihood") is not None
            else data.get("score")
        )
        spans: List[SuspectSpan] = []
        for frag in (data.get("fragments") or data.get("windows") or []):
            text = (frag.get("text") or frag.get("fragment") or "").strip()
            raw = frag.get("ai_likelihood")
            fscore = _coerce_score(raw if raw is not None else frag.get("score"))
            if text and fscore is not None and fscore >= HIGH_THRESHOLD and count_words(text) >= _MIN_SPAN_WORDS:
                spans.append(SuspectSpan(
                    quote=truncate_quote(text),
                    reason="Flagged by Pangram as likely AI-generated.",
                    confidence="medium",
                ))
        return score, spans

    def _gptzero(self, requests, body: str):
        resp = requests.post(
            _GPTZERO_URL, headers={"x-api-key": self.api_key},
            json={"document": body}, timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        docs = data.get("documents") or []
        if not docs:
            return None, []
        doc = docs[0]
        score = doc.get("completely_generated_prob")
        if score is None:
            cp = doc.get("class_probabilities") or {}
            score = cp.get("ai")
        score = _coerce_score(score)
        spans: List[SuspectSpan] = []
        for sent in (doc.get("sentences") or []):
            sscore = _coerce_score(sent.get("generated_prob"))
            if sent.get("highlight_sentence_for_ai") and sscore is not None and sscore >= HIGH_THRESHOLD:
                quote = (sent.get("sentence") or "").strip()
                # Respect the package's "never per-sentence" floor: only surface
                # substantial highlighted passages, not one-liners.
                if quote and count_words(quote) >= _MIN_SPAN_WORDS:
                    spans.append(SuspectSpan(
                        quote=truncate_quote(quote),
                        reason="Flagged by GPTZero as likely AI-generated.",
                        confidence="low",
                    ))
        return score, spans


def _coerce_score(value) -> Optional[float]:
    """Coerce to a probability in [0, 1]; None on malformed/out-of-range.

    Out-of-range values (e.g. a 0-100 scale, or a malformed > 1 number) are
    rejected rather than guessed — banding them would fabricate a false
    "high" AI-likelihood, the worst-case honesty failure. The caller treats
    None as insufficient_signal / inconclusive.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if 0.0 <= v <= 1.0 else None
