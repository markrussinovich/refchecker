"""Pluggable AI-generated-text detection for submitted manuscripts.

Three selectable backends:

* ``local``     — desklib DeBERTa, offline, calibrated (default; needs download)
* ``llm-judge`` — reuses the configured LLM provider (no download, uncalibrated)
* ``api``       — Pangram / GPTZero (opt-in, needs key + privacy consent)

All detection flows through :func:`run_detection`, which always returns an
:class:`AIDetectionResult` (never raises) so a detection failure can never
break the surrounding citation check.  See :mod:`base` for the honesty policy
(banding, abstention, disclaimer).
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import (
    AIDetectionResult,
    DetectionBackend,
    SuspectSpan,
    DISCLAIMER,
    MIN_WORDS,
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    make_unavailable,
)
from . import model_manager

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "local"
VALID_BACKENDS = ("local", "llm-judge", "api")


def build_detector(backend: str, *, check_id=None, **opts) -> Optional[DetectionBackend]:
    """Construct a detection backend by name, or None if unknown.

    ``check_id`` is threaded to the backend so its token/cost usage can be
    attributed to the right check in the usage meter.
    """
    backend = (backend or DEFAULT_BACKEND).lower()
    if backend == "local":
        from .local_backend import LocalDetectorBackend
        return LocalDetectorBackend(check_id=check_id)
    if backend in ("llm-judge", "llm"):
        from .llm_backend import LLMJudgeBackend
        return LLMJudgeBackend(
            provider=opts.get("provider"),
            api_key=opts.get("api_key"),
            endpoint=opts.get("endpoint"),
            model=opts.get("model"),
            check_id=check_id,
        )
    if backend == "api":
        from .api_backend import ApiBackend
        return ApiBackend(
            service=opts.get("service", "pangram"),
            api_key=opts.get("api_key"),
            consent=opts.get("consent", False),
            check_id=check_id,
        )
    logger.warning("Unknown AI-detection backend: %s", backend)
    return None


def run_detection(
    text: str,
    *,
    title: Optional[str] = None,
    backend: str = DEFAULT_BACKEND,
    check_id=None,
    **opts,
) -> AIDetectionResult:
    """Run the selected backend over manuscript body ``text``.

    Always returns a result; on any failure returns an "unavailable" result
    with a machine-readable ``abstain_reason``.
    """
    detector = build_detector(backend, check_id=check_id, **opts)
    if detector is None:
        return make_unavailable("unknown_backend", backend)
    try:
        return detector.detect(text, title=title)
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI detection (%s) raised: %s", backend, exc)
        return make_unavailable("detection_error", backend)


__all__ = [
    "AIDetectionResult",
    "DetectionBackend",
    "SuspectSpan",
    "DISCLAIMER",
    "MIN_WORDS",
    "HIGH_THRESHOLD",
    "MEDIUM_THRESHOLD",
    "DEFAULT_BACKEND",
    "VALID_BACKENDS",
    "build_detector",
    "run_detection",
    "model_manager",
]
