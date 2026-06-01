"""Lightweight per-process LLM usage + cost tracker.

Counts input / output tokens by (provider, model) for the lifetime of
the server process and exposes a snapshot through ``get_usage_totals``.
Persisted to disk so totals survive restarts.

Cost estimates come from a hand-curated ``PROVIDER_RATES`` table — these
are list-price USD-per-1K-tokens for popular models as of writing.
Anything not in the table is reported with ``cost_usd: None``.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import aiosqlite
except ImportError:  # tests
    aiosqlite = None

import logging
logger = logging.getLogger(__name__)

# (provider, model_prefix) -> {input_per_1k_usd, output_per_1k_usd}
PROVIDER_RATES: Dict[str, Dict[str, Dict[str, float]]] = {
    "openai": {
        "gpt-5": {"input_per_1k_usd": 0.005, "output_per_1k_usd": 0.015},
        "gpt-4o-mini": {"input_per_1k_usd": 0.00015, "output_per_1k_usd": 0.0006},
        "gpt-4o": {"input_per_1k_usd": 0.0025, "output_per_1k_usd": 0.01},
        "gpt-4.1-mini": {"input_per_1k_usd": 0.0004, "output_per_1k_usd": 0.0016},
        "gpt-4.1": {"input_per_1k_usd": 0.002, "output_per_1k_usd": 0.008},
        "o3-mini": {"input_per_1k_usd": 0.0011, "output_per_1k_usd": 0.0044},
        "o3": {"input_per_1k_usd": 0.002, "output_per_1k_usd": 0.008},
        "o1-mini": {"input_per_1k_usd": 0.003, "output_per_1k_usd": 0.012},
        "o1": {"input_per_1k_usd": 0.015, "output_per_1k_usd": 0.06},
    },
    "anthropic": {
        "claude-opus-4": {"input_per_1k_usd": 0.015, "output_per_1k_usd": 0.075},
        "claude-sonnet-4": {"input_per_1k_usd": 0.003, "output_per_1k_usd": 0.015},
        "claude-haiku-4": {"input_per_1k_usd": 0.0008, "output_per_1k_usd": 0.004},
        "claude-3-7-sonnet": {"input_per_1k_usd": 0.003, "output_per_1k_usd": 0.015},
        "claude-3-5-sonnet": {"input_per_1k_usd": 0.003, "output_per_1k_usd": 0.015},
        "claude-3-5-haiku": {"input_per_1k_usd": 0.0008, "output_per_1k_usd": 0.004},
        "claude-3-opus": {"input_per_1k_usd": 0.015, "output_per_1k_usd": 0.075},
        "claude-3-haiku": {"input_per_1k_usd": 0.00025, "output_per_1k_usd": 0.00125},
    },
    "google": {
        "gemini-2.5-pro": {"input_per_1k_usd": 0.00125, "output_per_1k_usd": 0.01},
        "gemini-2.5-flash": {"input_per_1k_usd": 0.000075, "output_per_1k_usd": 0.0003},
        "gemini-2.0-flash": {"input_per_1k_usd": 0.0001, "output_per_1k_usd": 0.0004},
        "gemini-1.5-pro": {"input_per_1k_usd": 0.00125, "output_per_1k_usd": 0.005},
        "gemini-1.5-flash": {"input_per_1k_usd": 0.000075, "output_per_1k_usd": 0.0003},
    },
}


def _rate_for(provider: str, model: str) -> Optional[Dict[str, float]]:
    """Best-prefix-match lookup; returns None when no rate is known."""
    provider_rates = PROVIDER_RATES.get((provider or "").lower())
    if not provider_rates or not model:
        return None
    model_l = model.lower()
    best = None
    best_len = -1
    for prefix, rate in provider_rates.items():
        if model_l.startswith(prefix) and len(prefix) > best_len:
            best = rate
            best_len = len(prefix)
    return best


_TOTALS: Dict[str, Dict[str, Any]] = {}
_LOCK = asyncio.Lock()


def _key(provider: str, model: str) -> str:
    return f"{(provider or '').lower()}::{model or 'unknown'}"


def record_usage(provider: str, model: str, input_tokens: int, output_tokens: int, call_kind: str = "extraction"):
    """Synchronous recorder — safe to call from inside provider impls."""
    if not provider:
        return
    k = _key(provider, model)
    entry = _TOTALS.setdefault(k, {
        "provider": provider,
        "model": model,
        "input_tokens": 0,
        "output_tokens": 0,
        "calls": 0,
        "by_kind": {},
    })
    entry["input_tokens"] += int(input_tokens or 0)
    entry["output_tokens"] += int(output_tokens or 0)
    entry["calls"] += 1
    by_kind = entry["by_kind"].setdefault(call_kind, {"calls": 0, "input": 0, "output": 0})
    by_kind["calls"] += 1
    by_kind["input"] += int(input_tokens or 0)
    by_kind["output"] += int(output_tokens or 0)


def get_usage_totals() -> Dict[str, Any]:
    """Snapshot the current usage table with cost estimates filled in."""
    items = []
    grand_input = 0
    grand_output = 0
    grand_cost: Optional[float] = 0.0
    for k, e in _TOTALS.items():
        rate = _rate_for(e["provider"], e["model"])
        cost_usd = None
        if rate:
            cost_usd = (
                e["input_tokens"] / 1000.0 * rate["input_per_1k_usd"]
                + e["output_tokens"] / 1000.0 * rate["output_per_1k_usd"]
            )
        else:
            grand_cost = None  # unknown rate → grand total becomes uncertain
        items.append({
            **e,
            "cost_usd": cost_usd,
            "rate_known": rate is not None,
        })
        grand_input += e["input_tokens"]
        grand_output += e["output_tokens"]
        if grand_cost is not None and cost_usd is not None:
            grand_cost += cost_usd
    items.sort(key=lambda x: x["calls"], reverse=True)
    return {
        "providers": items,
        "totals": {
            "input_tokens": grand_input,
            "output_tokens": grand_output,
            "cost_usd": grand_cost,
            "calls": sum(e["calls"] for e in _TOTALS.values()),
        },
    }


def reset_usage():
    _TOTALS.clear()


# ── Persistence ────────────────────────────────────────────────────────

_PERSIST_PATH: Optional[Path] = None


def configure_persistence(path: Path):
    global _PERSIST_PATH
    _PERSIST_PATH = Path(path)
    try:
        _PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _PERSIST_PATH.exists():
            data = json.loads(_PERSIST_PATH.read_text())
            if isinstance(data, dict):
                _TOTALS.update(data)
    except Exception as e:
        logger.debug("usage_tracker: failed to load persisted totals: %s", e)


def flush_persistence():
    if _PERSIST_PATH is None:
        return
    try:
        _PERSIST_PATH.write_text(json.dumps(_TOTALS, default=str))
    except Exception as e:
        logger.debug("usage_tracker: failed to persist totals: %s", e)


# ── Provider response helpers ─────────────────────────────────────────

def extract_openai_usage(response) -> Dict[str, int]:
    u = getattr(response, "usage", None)
    if not u:
        return {"input_tokens": 0, "output_tokens": 0}
    # `completion_tokens` already includes reasoning_tokens on o*/gpt-5
    # models (OpenAI bills them as output). `prompt_tokens` already
    # includes any cached prompt tokens — those are charged at a
    # discounted rate but still appear in prompt_tokens, so reporting
    # prompt_tokens here matches what the provider's dashboard shows
    # under "total tokens".
    return {
        "input_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
    }


def extract_anthropic_usage(response) -> Dict[str, int]:
    u = getattr(response, "usage", None)
    if not u:
        return {"input_tokens": 0, "output_tokens": 0}
    # Anthropic reports input_tokens SEPARATELY from cache_creation /
    # cache_read tokens. The provider bills all three, so the badge has
    # to add them — otherwise prompt-cached calls under-count by 10x+.
    # Cache reads are billed at ~0.1x and cache writes at ~1.25x of the
    # input rate; we lump them in here so the token count matches what
    # the user sees on their Anthropic dashboard. Cost-side refinement
    # can be added later if we ever start using caching in production.
    base_in = int(getattr(u, "input_tokens", 0) or 0)
    cache_w = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    cache_r = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    return {
        "input_tokens": base_in + cache_w + cache_r,
        "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
    }


def extract_gemini_usage(response) -> Dict[str, int]:
    meta = getattr(response, "usage_metadata", None)
    if not meta:
        return {"input_tokens": 0, "output_tokens": 0}
    return {
        "input_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(meta, "candidates_token_count", 0) or 0),
    }
