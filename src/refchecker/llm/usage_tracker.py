"""Per-check LLM token + cost accumulator.

Lightweight thread-safe singleton keyed by check_id (or 'default' when no
check is in scope). Each provider's `_call_llm` records the usage it
observes from the API response; the FastAPI layer exposes the accumulator
to the frontend so the Summary tab can render an LLM badge showing
tokens + dollars consumed by this check, broken down per flow.

Reset behavior: when a new check starts, `reset(check_id)` clears the
accumulator for that check so the badge starts at 0.
"""
from __future__ import annotations

import threading
from typing import Dict, Optional

# Price table — USD per 1M tokens. Keys are substring matches against the
# model id. Values are (input_per_million, output_per_million). Numbers
# are approximate and conservative for badge display; we don't bill on
# this. The lookup explicitly sorts by key length (longest first) so a
# specific key like "claude-3-5-sonnet" wins over the generic "claude-3".
_PRICES_PER_MILLION = [
    # 4-5 family (longer keys come first so they win over "claude-*-4")
    ("claude-opus-4-5", (15.0, 75.0)),
    ("claude-sonnet-4-5", (3.0, 15.0)),
    ("claude-haiku-4-5", (1.0, 5.0)),
    ("claude-opus-4", (15.0, 75.0)),
    ("claude-sonnet-4", (3.0, 15.0)),
    ("claude-haiku-4", (1.0, 5.0)),
    ("claude-3-5-sonnet", (3.0, 15.0)),
    ("claude-3-5-haiku", (0.80, 4.0)),
    ("claude-3-opus", (15.0, 75.0)),
    ("claude-3-sonnet", (3.0, 15.0)),
    ("claude-3-haiku", (0.25, 1.25)),
    # GPT-5.1 family
    ("gpt-5.1-mini", (0.25, 2.0)),
    ("gpt-5.1-nano", (0.05, 0.40)),
    ("gpt-5.1", (1.25, 10.0)),
    ("gpt-5-mini", (0.25, 2.0)),
    ("gpt-5-nano", (0.05, 0.40)),
    ("gpt-5", (1.25, 10.0)),
    ("gpt-4o-mini", (0.15, 0.60)),
    ("gpt-4o", (2.50, 10.0)),
    ("gpt-4.1-mini", (0.40, 1.60)),
    ("gpt-4.1-nano", (0.10, 0.40)),
    ("gpt-4.1", (2.0, 8.0)),
    ("gpt-4-turbo", (10.0, 30.0)),
    ("gpt-4", (30.0, 60.0)),
    ("gpt-3.5", (0.50, 1.50)),
    ("o4-mini", (1.10, 4.40)),
    ("o3-mini", (1.10, 4.40)),
    ("o3-pro", (20.0, 80.0)),
    ("o3", (10.0, 40.0)),
    ("o1-mini", (1.10, 4.40)),
    ("o1-pro", (150.0, 600.0)),
    ("o1", (15.0, 60.0)),
    # Gemini 3.x
    ("gemini-3-pro", (1.25, 10.0)),
    ("gemini-3-flash", (0.30, 2.50)),
    ("gemini-2.5-flash", (0.30, 2.50)),
    ("gemini-2.5-pro", (1.25, 10.0)),
    ("gemini-2.0-flash", (0.075, 0.30)),
    ("gemini-1.5-flash", (0.075, 0.30)),
    ("gemini-1.5-pro", (1.25, 5.0)),
    ("gemini", (0.50, 2.0)),  # fallback
]
# Sorted longest-key-first so substring matches resolve specifically.
_PRICES_BY_LENGTH = sorted(_PRICES_PER_MILLION, key=lambda kv: -len(kv[0]))


def estimate_cost_usd(model: Optional[str], input_tokens: int, output_tokens: int) -> float:
    """Cheap cost estimate from a model id and token counts.

    Unknown models default to a middle-of-the-road rate so the badge isn't
    silently zero for newly-released models.
    """
    m = (model or "").lower()
    in_rate, out_rate = 1.0, 4.0
    for key, rates in _PRICES_BY_LENGTH:
        if key in m:
            in_rate, out_rate = rates
            break
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0


_lock = threading.Lock()
_state: Dict[str, Dict] = {}

# When a check is running, the FastAPI layer sets this to the current
# check_id so providers that don't know about checks can still attribute
# their calls. Threadlocal so concurrent checks don't bleed into each other.
_current = threading.local()


def set_current_check(check_id: Optional[str]) -> None:
    """Set the active check id for the current thread. Pass None to clear."""
    _current.check_id = check_id


def get_current_check() -> Optional[str]:
    return getattr(_current, "check_id", None)


def _key(check_id: Optional[str]) -> str:
    return str(check_id) if check_id is not None else "default"


def reset(check_id: Optional[str]) -> None:
    """Clear the accumulator for a check. Called at the start of each run."""
    k = _key(check_id)
    with _lock:
        _state[k] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "calls": 0,
            "by_flow": {},  # flow -> {input_tokens, output_tokens, cost_usd, calls}
            "by_model": {},  # model -> same shape (without calls breakdown)
        }


def record(
    *,
    check_id: Optional[str] = None,
    model: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    flow: str = "other",
    cost_usd: Optional[float] = None,
) -> None:
    """Add one LLM call to the accumulator.

    `flow` is one of: extract | verify | hallucination | suggest | graph |
    reverify | other. Anything not recognised is bucketed under 'other'.
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return
    cost = cost_usd if cost_usd is not None else estimate_cost_usd(model, input_tokens, output_tokens)
    k = _key(check_id if check_id is not None else get_current_check())
    with _lock:
        bucket = _state.setdefault(k, {
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "calls": 0, "by_flow": {}, "by_model": {},
        })
        bucket["input_tokens"] += int(input_tokens)
        bucket["output_tokens"] += int(output_tokens)
        bucket["cost_usd"] += float(cost)
        bucket["calls"] += 1
        fb = bucket["by_flow"].setdefault(flow or "other", {
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0,
        })
        fb["input_tokens"] += int(input_tokens)
        fb["output_tokens"] += int(output_tokens)
        fb["cost_usd"] += float(cost)
        fb["calls"] += 1
        if model:
            mb = bucket["by_model"].setdefault(model, {
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            })
            mb["input_tokens"] += int(input_tokens)
            mb["output_tokens"] += int(output_tokens)
            mb["cost_usd"] += float(cost)


def snapshot(check_id: Optional[str]) -> Dict:
    """Return a copy of the accumulator for the given check."""
    k = _key(check_id)
    with _lock:
        bucket = _state.get(k)
        if not bucket:
            return {
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                "calls": 0, "by_flow": {}, "by_model": {},
            }
        # Shallow copy with copied dicts to avoid mutation races
        return {
            "input_tokens": bucket["input_tokens"],
            "output_tokens": bucket["output_tokens"],
            "cost_usd": bucket["cost_usd"],
            "calls": bucket["calls"],
            "by_flow": {k: dict(v) for k, v in bucket["by_flow"].items()},
            "by_model": {k: dict(v) for k, v in bucket["by_model"].items()},
        }


class FlowScope:
    """Context manager that tags any `record(...)` calls made on this
    thread with a particular flow label, so call-sites that don't know
    the flow (deep inside provider code) can still attribute properly.
    """
    def __init__(self, flow: str):
        self.flow = flow
        self._prev = None

    def __enter__(self):
        self._prev = getattr(_current, "flow", None)
        _current.flow = self.flow
        return self

    def __exit__(self, exc_type, exc, tb):
        _current.flow = self._prev


def get_current_flow() -> str:
    return getattr(_current, "flow", None) or "other"
