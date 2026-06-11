"""Multi-detector run + honest side-by-side comparison (R61 / §14, item 2).

Run **one or more** installed Tier-1 detectors over the same manuscript and
return each detector's OWN verdict, plus a comparison summary computed in plain
code. There is deliberately **no synthetic "ensemble truth"**: disagreement
between detectors is surfaced as signal, never averaged away into a single
fabricated number. An uninstalled / non-installable detector ABSTAINS — it
never reports a score.

The per-detector result reuses the existing honesty machinery in
:mod:`base` and :mod:`local_backend`:

* windowed document scoring (mean over >= MIN_WORDS windows),
* per-detector score→band thresholds (the registry ``threshold``),
* per-sentence scoring (descriptive, capped, advisory — not a guilt prob).

The comparison summary reports:

* ``per_sentence`` — for each shared sentence, every detector's band + the
  agreement count (how many detectors landed on the modal band),
* ``pairwise_agreement`` — for each detector pair, the fraction of shared
  sentences where their bands matched,
* ``band_agreement`` — whether the detectors' DOCUMENT bands all matched.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence

from .base import (
    AIDetectionResult,
    BAND_HIGH,
    BAND_MEDIUM,
    BAND_LOW,
    DISCLAIMER,
    OPERATING_POINT,
    band_from_probability,
    band_rank,
    iter_windows,
    make_inconclusive,
    make_unavailable,
    prepared_text,
    should_abstain,
)
from . import model_manager

logger = logging.getLogger(__name__)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _band_for_score(score: float, threshold: Optional[float]) -> str:
    """Band a score using this detector's OWN high threshold.

    Falls back to the shared :func:`band_from_probability` when the registry
    gives no per-detector threshold. The medium cut is the global default; only
    the high cut is per-detector (that's the one the registry calibrates).
    """
    from .base import MEDIUM_THRESHOLD
    if threshold is None:
        return band_from_probability(score)
    if score >= float(threshold):
        return BAND_HIGH
    if score >= MEDIUM_THRESHOLD:
        return BAND_MEDIUM
    return BAND_LOW


def _document_sentences(body: str, cap: int = 40) -> List[str]:
    """A bounded list of assessable sentences shared across detectors.

    The SAME sentence set is scored by every detector so the per-sentence
    agreement view compares like-for-like. Sentences are filtered to a readable
    length band (mirrors local_backend's _viz sentence filter) and capped so a
    long document can't explode the per-detector inference budget.
    """
    out: List[str] = []
    seen = set()
    for s in _SENT_SPLIT.split(body):
        s = s.strip()
        if 40 <= len(s) <= 320 and s not in seen:
            seen.add(s)
            out.append(s)
            if len(out) >= cap:
                break
    return out


def _run_one(key: str, body: str, wc: int, sentences: Sequence[str]) -> Dict:
    """Score the document + shared sentences with detector ``key``.

    Returns a dict shaped like ``AIDetectionResult.to_dict()`` plus a
    ``per_sentence`` list (one entry per shared sentence: text, score, band).
    Abstains (unavailable / inconclusive) honestly — NEVER a fabricated number.
    """
    entry = model_manager.get_detector(key)
    if not entry:
        d = make_unavailable("unknown_detector", key, wc).to_dict()
        d["key"] = key
        d["per_sentence"] = []
        return d
    label = str(entry.get("label", key))
    threshold = entry.get("threshold")

    if not entry.get("installable"):
        r = make_unavailable("detector_not_runnable", key, wc)
        d = r.to_dict()
        d.update({"key": key, "label": label, "tier": entry.get("tier"),
                  "threshold": threshold, "per_sentence": []})
        return d
    if not model_manager.is_detector_installed(key):
        r = make_unavailable("model_not_installed", key, wc)
        d = r.to_dict()
        d.update({"key": key, "label": label, "tier": entry.get("tier"),
                  "threshold": threshold, "per_sentence": []})
        return d
    if not model_manager.deps_available():
        r = make_unavailable("deps_not_installed", key, wc)
        d = r.to_dict()
        d.update({"key": key, "label": label, "tier": entry.get("tier"),
                  "threshold": threshold, "per_sentence": []})
        return d

    # Only score windows that independently clear the reliability floors, same
    # rule as LocalDetectorBackend — keeps equation/citation-dense windows out.
    kept = [w for w in iter_windows(body) if should_abstain(w) is None]
    if not kept:
        r = make_inconclusive("insufficient_signal", key, wc)
        d = r.to_dict()
        d.update({"key": key, "label": label, "tier": entry.get("tier"),
                  "threshold": threshold, "per_sentence": []})
        return d

    try:
        from . import local_backend
        engine = local_backend.load(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("detector %s load failed: %s", key, exc)
        r = make_unavailable("model_load_failed", key, wc, detail=str(exc)[:300])
        d = r.to_dict()
        d.update({"key": key, "label": label, "tier": entry.get("tier"),
                  "threshold": threshold, "per_sentence": []})
        return d

    try:
        probs = [float(engine.score(w)) for w in kept]
    except Exception as exc:  # noqa: BLE001
        logger.warning("detector %s inference failed: %s", key, exc)
        r = make_unavailable("inference_failed", key, wc, detail=str(exc)[:300])
        d = r.to_dict()
        d.update({"key": key, "label": label, "tier": entry.get("tier"),
                  "threshold": threshold, "per_sentence": []})
        return d

    doc_score = round(sum(probs) / len(probs), 3)
    raw_band = _band_for_score(doc_score, threshold)
    band = raw_band
    # Same single-window cap as the local backend: a lone high window stays
    # advisory (medium) so one noisy window never drives a 'high' verdict.
    if band == BAND_HIGH and len(kept) < 2:
        band = BAND_MEDIUM
    surfaced = None if band_rank(band) < band_rank(raw_band) else doc_score

    per_sentence = []
    for s in sentences:
        try:
            sc = round(float(engine.score(s)), 3)
        except Exception:  # noqa: BLE001
            continue
        per_sentence.append({
            "text": s,
            "score": sc,
            "band": _band_for_score(sc, threshold),
        })

    result = AIDetectionResult(
        band=band,
        overall_score=surfaced,
        confidence="medium",
        summary=f"{label}: document score {doc_score:.2f} over {len(kept)} windows.",
        backend_used=f"local:{key}",
        model_version=f"local:{entry.get('repo')}",
        operating_point=OPERATING_POINT,
        word_count=wc,
        disclaimer=DISCLAIMER,
    )
    d = result.to_dict()
    d.update({
        "key": key,
        "label": label,
        "tier": entry.get("tier"),
        "threshold": threshold,
        "per_sentence": per_sentence,
    })
    return d


def _comparison_summary(results: List[Dict], sentences: List[str]) -> Dict:
    """Compute agreement metrics across detectors in PLAIN code (no ensemble).

    Only detectors that actually produced a scored band participate; abstaining
    detectors are excluded from agreement math (they have no verdict to compare).
    """
    scored = [r for r in results if r.get("band") in (BAND_LOW, BAND_MEDIUM, BAND_HIGH)]
    keys = [r["key"] for r in scored]

    # Document-level band agreement.
    doc_bands = {r["key"]: r["band"] for r in scored}
    band_agreement = len(set(doc_bands.values())) <= 1 if scored else False

    # Per-sentence agreement: align each detector's per-sentence band by text.
    by_text: Dict[str, Dict[str, str]] = {}
    for r in scored:
        for ps in r.get("per_sentence", []):
            by_text.setdefault(ps["text"], {})[r["key"]] = ps["band"]

    per_sentence = []
    for s in sentences:
        bands = by_text.get(s)
        if not bands:
            continue
        # Modal band + how many detectors landed on it.
        counts: Dict[str, int] = {}
        for b in bands.values():
            counts[b] = counts.get(b, 0) + 1
        modal_band = max(counts, key=lambda b: counts[b])
        agreement_count = counts[modal_band]
        per_sentence.append({
            "text": s,
            "bands": dict(bands),                 # {detector_key: band}
            "modal_band": modal_band,
            "agreement_count": agreement_count,   # how many agree on the modal band
            "detector_count": len(bands),
            "unanimous": agreement_count == len(bands),
        })

    # Pairwise agreement: fraction of shared sentences where the pair's bands match.
    pairwise = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            shared = matched = 0
            for s in sentences:
                bands = by_text.get(s, {})
                if a in bands and b in bands:
                    shared += 1
                    if bands[a] == bands[b]:
                        matched += 1
            pairwise.append({
                "pair": [a, b],
                "shared_sentences": shared,
                "matched": matched,
                "agreement": round(matched / shared, 3) if shared else None,
            })

    return {
        "detectors_compared": keys,
        "document_bands": doc_bands,
        "band_agreement": band_agreement,
        "per_sentence": per_sentence,
        "pairwise_agreement": pairwise,
    }


def run_detectors(text_or_pages, keys: Sequence[str]) -> Dict:
    """Run the selected detectors over ``text_or_pages`` and compare them.

    ``text_or_pages`` is the manuscript body string (or a list of page strings,
    which are joined). ``keys`` is the ordered list of detector keys to run.

    Returns::

        {
          "detectors": [ <per-detector result dict>, ... ],
          "comparison": { ...agreement summary... },
          "word_count": int,
          "disclaimer": str,
        }

    Honesty contract: an uninstalled / non-installable detector appears in
    ``detectors`` with an "unavailable" band and NO score — it is never given a
    fabricated number and never participates in the agreement math.
    """
    if isinstance(text_or_pages, (list, tuple)):
        text = "\n\n".join(str(p) for p in text_or_pages if p)
    else:
        text = str(text_or_pages or "")

    body, wc = prepared_text(text)
    # De-dupe keys while preserving order; drop empties.
    seen = set()
    ordered_keys: List[str] = []
    for k in (keys or []):
        k = (k or "").strip().lower()
        if k and k not in seen:
            seen.add(k)
            ordered_keys.append(k)
    if not ordered_keys:
        ordered_keys = [model_manager.DEFAULT_DETECTOR]

    abstain_reason = should_abstain(body)
    sentences = [] if abstain_reason else _document_sentences(body)

    results: List[Dict] = []
    for key in ordered_keys:
        if abstain_reason:
            # Body itself is below the reliability floor → every detector
            # abstains identically (honest, no fabricated numbers).
            entry = model_manager.get_detector(key)
            r = (make_unavailable("no_body_text", key, wc)
                 if abstain_reason == "no_body_text"
                 else make_inconclusive(abstain_reason, key, wc))
            d = r.to_dict()
            d.update({
                "key": key,
                "label": str((entry or {}).get("label", key)),
                "tier": (entry or {}).get("tier"),
                "threshold": (entry or {}).get("threshold"),
                "per_sentence": [],
            })
            results.append(d)
        else:
            results.append(_run_one(key, body, wc, sentences))

    comparison = _comparison_summary(results, sentences)
    return {
        "detectors": results,
        "comparison": comparison,
        "word_count": wc,
        "disclaimer": DISCLAIMER,
    }
