"""Local calibrated detector backend (default engine).

Runs the desklib ``ai-text-detector-v1.01`` model (DeBERTa-v3, MIT) entirely
offline.  The default model ships **safetensors**, so it runs via
``transformers`` + ``torch``; the ``onnxruntime`` path is used only when a
``model.onnx`` (with a classifier head) is present.  All ML imports are lazy
and wrapped — a missing dependency or un-downloaded model yields an
"unavailable" result, never a crash.

Scoring is windowed (>= ~350-word windows, 50 % overlap).  The document score
is the **mean** of window probabilities (a conservative aggregate — taking the
max over many windows would inflate false positives).  A span is surfaced only
when it AND an overlapping neighbour both clear the high threshold, so single
noisy windows never produce an accusation.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from .base import (
    AIDetectionResult,
    DetectionBackend,
    SuspectSpan,
    BAND_MEDIUM,
    HIGH_THRESHOLD,
    OPERATING_POINT,
    DISCLAIMER,
    BAND_HIGH,
    band_from_probability,
    band_rank,
    iter_windows,
    make_inconclusive,
    make_unavailable,
    prepared_text,
    record_detection_usage,
    should_abstain,
    truncate_quote,
)
from . import model_manager

logger = logging.getLogger(__name__)

_MAX_TOKENS = 768  # per-window truncation for the encoder

# Module-level model cache so we load weights once per process. Guarded by a
# lock because concurrent batch checks call _get_engine() from multiple
# asyncio.to_thread worker threads.
_engine = None
_engine_lock = threading.Lock()


def _ai_positive_index(id2label: Optional[Dict]) -> Optional[int]:
    """Pick the logit index whose label denotes AI/generated text.

    Returns the index, or None if it cannot be determined unambiguously (e.g.
    ``LABEL_0``/``LABEL_1``). Callers MUST abstain rather than guess when this
    returns None — guessing can invert the score and flag human text as AI,
    the worst possible honesty failure for this feature.
    """
    if not id2label:
        return None
    keys = ("fake", "generated", "machine", "llm", "gpt", "synthetic", "chatgpt")
    matches = []
    for idx, label in id2label.items():
        lab = str(label).strip().lower()
        if lab == "ai" or lab.startswith(("ai-", "ai_", "ai ")) or any(k in lab for k in keys):
            matches.append(int(idx))
    return matches[0] if len(matches) == 1 else None


class LocalDetectorBackend(DetectionBackend):
    name = "local"

    def __init__(self, check_id=None):
        self.model_version = f"local:{model_manager.MODEL_REPO}"
        self.check_id = check_id

    @property
    def available(self) -> bool:
        return model_manager.is_model_installed() and model_manager.deps_available()

    def detect(self, text: str, *, title: Optional[str] = None) -> AIDetectionResult:
        body, wc = prepared_text(text)
        if not model_manager.is_model_installed():
            return make_unavailable("model_not_installed", self.name, wc)
        if not model_manager.deps_available():
            return make_unavailable("deps_not_installed", self.name, wc)
        reason = should_abstain(body)
        if reason:
            return make_inconclusive(reason, self.name, wc)

        try:
            engine = _get_engine()
        except Exception as exc:  # noqa: BLE001
            detail = _format_load_error(exc)
            logger.warning("Local detector load failed: %s", detail)
            try:
                from . import diagnostics
                diagnostics.record({"event": "model_load_failed", "detail": detail})
            except Exception:  # noqa: BLE001
                pass
            return make_unavailable("model_load_failed", self.name, wc, detail=detail)

        # Only score windows that independently clear the SAME reliability
        # floors the document had to clear (>= MIN_WORDS prose, non-prose
        # fraction <= the abstain threshold). This prevents an equation- /
        # citation-dense window inside an otherwise-prose manuscript from
        # being scored and surfaced as a flagged passage — detectors are
        # documented as unreliable on exactly that terrain.
        # Keep each retained window's ORIGINAL position so span corroboration
        # can require *physical* adjacency (overlap), not just list adjacency
        # after non-prose windows were dropped.
        kept = [(i, w) for i, w in enumerate(iter_windows(body)) if should_abstain(w) is None]
        if not kept:
            return make_inconclusive("insufficient_signal", self.name, wc)
        orig_idx = [i for i, _ in kept]
        windows = [w for _, w in kept]
        try:
            probs = [engine.score(w) for w in windows]
        except Exception as exc:  # noqa: BLE001
            detail = _format_load_error(exc)
            logger.warning("Local detector inference failed: %s", detail)
            return make_unavailable("inference_failed", self.name, wc, detail=detail)

        doc_score = round(sum(probs) / len(probs), 3)
        raw_band = band_from_probability(doc_score)
        band = raw_band
        # A standalone 'high' document band requires >= 2 assessable windows
        # (the mean already needed broad agreement to clear HIGH_THRESHOLD). A
        # lone high-scoring window stays advisory — cap it at medium so a single
        # noisy window never drives a 'high' verdict. (Span surfacing applies a
        # stricter physical-adjacency rule on top of this; see _agreeing_spans.)
        if band == BAND_HIGH and len(windows) < 2:
            band = BAND_MEDIUM
        # When that cap lowered the band, suppress the surfaced score so the UI
        # never shows "Medium · score 90" — reading a number higher than the
        # (capped) band is confusing dissonance. Mirrors the LLM backend.
        surfaced_score = None if band_rank(band) < band_rank(raw_band) else doc_score

        # Local inference is free: record the processed word count for the
        # usage meter (tokens proxy) with $0 cost.
        record_detection_usage(self.check_id, self.model_version, input_tokens=wc, cost_usd=0.0)

        spans = _agreeing_spans(windows, probs, orig_idx) if band_rank(band) >= band_rank(BAND_MEDIUM) else []

        return AIDetectionResult(
            band=band,
            overall_score=surfaced_score,
            confidence="medium",
            summary=_summary(band, surfaced_score, len(windows)),
            spans=spans,
            backend_used=self.name,
            model_version=self.model_version,
            operating_point=OPERATING_POINT,
            word_count=wc,
            disclaimer=DISCLAIMER,
        )


def _agreeing_spans(windows: List[str], probs: List[float],
                    orig_idx: List[int]) -> List[SuspectSpan]:
    """Surface windows above the high threshold that have a high neighbour.

    Corroboration requires a neighbour that is BOTH list-adjacent AND
    physically adjacent in the document (original window index differs by 1, so
    the two windows actually overlap). A dropped non-prose window between two
    retained ones breaks the chain — preventing a spurious "agreement" drawn
    from two passages that don't actually border each other.
    """
    spans: List[SuspectSpan] = []
    n = len(windows)
    for i, p in enumerate(probs):
        if p < HIGH_THRESHOLD:
            continue
        neighbour_high = (
            (i > 0 and probs[i - 1] >= HIGH_THRESHOLD and orig_idx[i] - orig_idx[i - 1] == 1)
            or (i < n - 1 and probs[i + 1] >= HIGH_THRESHOLD and orig_idx[i + 1] - orig_idx[i] == 1)
        )
        if not neighbour_high:
            continue
        spans.append(SuspectSpan(
            quote=truncate_quote(windows[i]),
            reason="This passage scored above the high-likelihood threshold.",
            confidence="medium",
        ))
        if len(spans) >= 6:
            break
    return spans


def _summary(band: str, score, n_windows: int) -> str:
    base = {
        "low": "No strong indicators of AI-generated prose.",
        "medium": "Some indicators present; not conclusive.",
        "high": "Multiple indicators present — this is NOT proof of AI authorship.",
    }.get(band, "")
    if score is None:
        return f"{base} (assessed {n_windows} text window{'s' if n_windows != 1 else ''})"
    return f"{base} (model score {score:.2f} over {n_windows} text windows)"


# ── Inference engine (lazy) ───────────────────────────────────────────────

def _format_load_error(exc: Exception) -> str:
    """Compact, user-actionable one-liner for a load/inference exception.

    Includes the exception type and message, and — for the common
    'model directory not found / missing config.json' case — the resolved
    model path so a path mismatch is immediately obvious in the UI.
    """
    msg = f"{type(exc).__name__}: {exc}".strip()
    try:
        p = model_manager.model_path()
        if isinstance(exc, (FileNotFoundError, OSError)) or "config.json" in msg or "does not appear" in msg:
            msg = f"{msg} (model path: {p})"
    except Exception:  # noqa: BLE001
        pass
    return msg[:500]


def _get_engine():
    global _engine
    if _engine is not None:
        return _engine
    # Double-checked locking: under a cold-start batch, several worker threads
    # can reach here at once; without the lock each would load DeBERTa weights
    # (hundreds of MB) in parallel — a memory spike that defeats "load once".
    with _engine_lock:
        if _engine is not None:
            return _engine
        # Defensive: make the pip-installed runtime importable even if detect()
        # was reached without a prior deps_available() call (e.g. a fresh worker
        # thread). deps_available() also does this, but calling it here too is
        # idempotent and closes the "runtime not on sys.path at load time" gap.
        try:
            from . import runtime_manager
            runtime_manager.ensure_on_path()
        except Exception as exc:  # noqa: BLE001
            logger.debug("ensure_on_path before engine load failed: %s", exc)
        path = str(model_manager.model_path())
        onnx_file = model_manager.model_path() / "model.onnx"
        built = None
        if onnx_file.is_file():
            try:
                built = _OnnxEngine(path, str(onnx_file))
            except Exception as exc:  # noqa: BLE001
                logger.warning("ONNX engine unavailable, falling back to torch: %s", exc)
        if built is None:
            built = _TorchEngine(path)
        _engine = built
        return _engine


def _load_checkpoint_state_dict(model_dir: str):
    """Load a checkpoint's tensors directly (safetensors preferred, then .bin).

    Returns a state-dict mapping or None if no weight file is present. Avoids
    the version-sensitive ``from_pretrained`` path so the desklib model loads
    consistently across transformers releases.
    """
    import os
    st = os.path.join(model_dir, "model.safetensors")
    if os.path.isfile(st):
        from safetensors.torch import load_file
        return load_file(st)
    for fname in ("pytorch_model.bin", "model.bin"):
        binp = os.path.join(model_dir, fname)
        if os.path.isfile(binp):
            import torch
            return torch.load(binp, map_location="cpu")
    return None


class _TorchEngine:
    """transformers + torch runtime for the desklib custom model."""

    def __init__(self, model_dir: str):
        import warnings
        import torch
        from transformers import AutoTokenizer, AutoConfig, AutoModel
        import torch.nn as nn

        self.torch = torch
        # Suppress warnings around EVERY transformers call below. A warning
        # emitted while a frame of THIS module is on the stack makes the warnings
        # formatter read this file's source; in a PyInstaller bundle that read
        # used to raise FileNotFoundError (see the longer note below). The
        # tokenizer/config loads warn too, so they must be wrapped as well — not
        # just model construction. (Source is also now shipped in the bundle as a
        # second layer of defence; see the spec's `.py` datas block.)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.tokenizer = AutoTokenizer.from_pretrained(model_dir)

        # Plain nn.Module — deliberately NOT a transformers PreTrainedModel.
        # Subclassing PreTrainedModel dragged in its version-fragile construction
        # surface (init_weights/tie_weights → `all_tied_weights_keys`,
        # `_tied_weights_keys`, post_init, ignore_mismatched_sizes …), which
        # breaks differently on every transformers release the user happens to
        # have pip-installed into the runtime. We only need an encoder + a linear
        # head + forward, and we load the weights ourselves with
        # load_state_dict(strict=False) — so a bare nn.Module is both sufficient
        # and immune to that API drift (verified: identical scores).
        class _DesklibModel(nn.Module):
            def __init__(self, config):
                super().__init__()
                self.model = AutoModel.from_config(config)
                self.classifier = nn.Linear(config.hidden_size, 1)

            def forward(self, input_ids, attention_mask=None, **_):
                outputs = self.model(input_ids, attention_mask=attention_mask)
                last_hidden = outputs[0]
                mask = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
                summed = torch.sum(last_hidden * mask, 1)
                counts = torch.clamp(mask.sum(1), min=1e-9)
                pooled = summed / counts
                return self.classifier(pooled)

        self._ai_index: Optional[int] = None
        self._std = None

        # Load the desklib checkpoint by building the architecture and loading
        # the weights DIRECTLY from the checkpoint file — version-robust.
        #
        # The HF `from_pretrained` dance fails on some transformers versions and
        # silently falls back to a sequence-classification head whose
        # [num_labels, hidden] classifier mismatches the desklib [1, hidden]
        # head — producing the "You set ignore_mismatched_sizes to False"
        # RuntimeError users hit. Loading the state dict ourselves and applying
        # it with strict=False sidesteps that machinery entirely (verified to
        # produce scores identical to a successful from_pretrained load).
        # Build + load INSIDE catch_warnings. A warning emitted from a frame in
        # this module (e.g. transformers' weight-init notice during
        # `_DesklibModel.__init__`) makes the warnings machinery read this file's
        # SOURCE to format the message. In a PyInstaller bundle the `.py` source
        # is not extracted, so that read raises
        # `FileNotFoundError: …/_MEIxxxx/refchecker/ai_detection/local_backend.py`
        # which surfaced as "model failed to load". Suppressing warnings here
        # removes the source-format step entirely (we do our own strict checks).
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            config = AutoConfig.from_pretrained(model_dir)
        state_dict = _load_checkpoint_state_dict(model_dir)

        if state_dict is not None and any(k.startswith("classifier") for k in state_dict):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = _DesklibModel(config)
                result = model.load_state_dict(state_dict, strict=False)
            missing = list(getattr(result, "missing_keys", []) or [])
            missing_clf = [k for k in missing if k.startswith("classifier")]
            missing_enc = [k for k in missing if k.startswith("model.")]
            # Refuse to score with a partially-random model (a random classifier
            # head could band human text high).
            if missing_clf or missing_enc:
                raise ValueError(
                    "desklib weights did not load cleanly (missing classifier="
                    f"{missing_clf}, missing {len(missing_enc)} encoder tensors); "
                    "refusing to score with a partially-initialised model."
                )
            model.eval()
            self.model = model
        else:
            # Not the desklib checkpoint — try a standard sequence-classification
            # head (e.g. a user-supplied alternative detector model).
            from transformers import AutoModelForSequenceClassification
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._std = AutoModelForSequenceClassification.from_pretrained(model_dir)
            self.model = None
            self._std.eval()
            num_labels = int(getattr(self._std.config, "num_labels", 1) or 1)
            if num_labels > 1:
                self._ai_index = _ai_positive_index(getattr(self._std.config, "id2label", None))
                if self._ai_index is None:
                    # Refuse to guess which class is "AI" — guessing can invert
                    # the score and flag human text as AI.
                    raise ValueError(
                        "Cannot determine the AI-positive class from the model's "
                        "id2label; refusing to guess. Use a single-logit detector "
                        "or a model with clearly labelled classes."
                    )

    def score(self, text: str) -> float:
        import warnings
        torch = self.torch
        # Same frozen-bundle guard as __init__: a warning emitted from the
        # tokenizer or from `_DesklibModel.forward` (this module) would try to
        # read the missing source file. Suppress so inference never raises
        # FileNotFoundError.
        with warnings.catch_warnings(), torch.no_grad():
            warnings.simplefilter("ignore")
            enc = self.tokenizer(
                text, truncation=True, max_length=_MAX_TOKENS, return_tensors="pt"
            )
            if self.model is not None:
                logit = self.model(enc["input_ids"], attention_mask=enc["attention_mask"])
                return float(torch.sigmoid(logit).squeeze().item())
            out = self._std(**enc).logits
            if out.shape[-1] == 1:
                return float(torch.sigmoid(out).squeeze().item())
            probs = torch.softmax(out, dim=-1).squeeze()
            return float(probs[self._ai_index].item())


class _OnnxEngine:
    """onnxruntime runtime (used only if a model.onnx with a head exists)."""

    def __init__(self, model_dir: str, onnx_path: str):
        import warnings
        import onnxruntime as ort
        from transformers import AutoTokenizer, AutoConfig
        import numpy as np

        self.np = np
        # Same frozen-bundle guard as _TorchEngine: suppress warnings around the
        # transformers calls so the formatter never reads this module's source.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.session.get_inputs()}
        # Resolve the AI-positive class index from the config for multi-class
        # heads (single-logit heads use sigmoid and ignore this).
        self._ai_index: Optional[int] = None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cfg = AutoConfig.from_pretrained(model_dir)
            if int(getattr(cfg, "num_labels", 1) or 1) > 1:
                self._ai_index = _ai_positive_index(getattr(cfg, "id2label", None))
        except Exception:  # noqa: BLE001
            self._ai_index = None

    def score(self, text: str) -> float:
        np = self.np
        enc = self.tokenizer(
            text, truncation=True, max_length=_MAX_TOKENS, return_tensors="np"
        )
        feeds = {k: v for k, v in enc.items() if k in self.input_names}
        out = self.session.run(None, feeds)[0]
        arr = np.asarray(out).reshape(-1)
        if arr.size == 1:
            return float(1.0 / (1.0 + np.exp(-arr[0])))
        if self._ai_index is None:
            raise ValueError(
                "Multi-class ONNX detector has no resolvable AI-positive class; "
                "refusing to guess which logit means 'AI'."
            )
        e = np.exp(arr - arr.max())
        return float((e / e.sum())[self._ai_index])
