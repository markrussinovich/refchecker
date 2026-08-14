"""Author hover-card metrics — h-index AND i10-index (POST /api/authors/profile).

Google Scholar publishes no API, so its specific h/i10 numbers are not
obtainable. OpenAlex, however, exposes ``summary_stats.i10_index`` alongside
``h_index`` under CC0, and Semantic Scholar does not expose i10 at all. The
endpoint therefore queries BOTH providers when both ids are known and merges
them, keeping S2 authoritative for everything it reports and letting OpenAlex
fill only the gaps (chiefly the i10-index).

These tests pin the behaviours that are easy to regress:
  * i10-index surfaces for an S2-primary author (the merge actually happens).
  * S2's numbers are never overwritten by OpenAlex's different corpus.
  * Each metric carries the source it came from, so the UI can say which is
    which instead of implying the two are comparable.
  * The cache key covers BOTH ids (same S2 id with/without an OpenAlex id must
    not serve the same payload).
  * One provider failing never sinks the other's data.

``backend.main`` cannot be imported wholesale (it pulls the full refchecker
stack), so — as in ``tests/unit/test_author_profile.py`` — only the
author-profile functions are lifted out of ``backend/main.py`` via ``ast`` and
exec'd into an isolated namespace wired to an offline ``httpx.MockTransport``.
The logic under test is the real shipped code; only its HTTP calls are doubled.
"""

import ast
import asyncio
from pathlib import Path

import httpx
import pytest

_MAIN_PATH = Path(__file__).resolve().parents[2] / "backend" / "main.py"

_WANTED = [
    "_noop_none",
    "_fetch_s2_author",
    "_fetch_openalex_author",
    "_merge_author_profiles",
    "_fetch_openalex_author_metrics",
    "author_profile",
]


class _NullLogger:
    def __getattr__(self, _name):
        def _noop(*_a, **_k):
            return None
        return _noop


def _load_namespace():
    tree = ast.parse(_MAIN_PATH.read_text(encoding="utf-8"), filename=str(_MAIN_PATH))
    wanted = {}
    model = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _WANTED:
            wanted[node.name] = node
        if isinstance(node, ast.ClassDef) and node.name == "_AuthorProfileRequest":
            model = node
    missing = [n for n in _WANTED if n not in wanted]
    assert not missing, f"author-profile functions not found in main.py: {missing}"
    assert model is not None, "_AuthorProfileRequest model not found"

    for node in wanted.values():
        node.decorator_list = []

    body = [model] + [wanted[n] for n in _WANTED]
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    code = compile(module, filename=str(_MAIN_PATH), mode="exec")

    from typing import Any, Dict, List, Optional
    from pydantic import BaseModel

    async def _no_key(*_a, **_k):
        return None

    ns = {
        "Optional": Optional, "Dict": Dict, "Any": Any, "List": List,
        "BaseModel": BaseModel,
        "asyncio": asyncio,
        "logger": _NullLogger(),
        "_resolve_semantic_scholar_api_key": _no_key,
        "Depends": (lambda dep=None: None),
        "require_user": None,
        "UserInfo": object,
        "_AUTHOR_PROFILE_CACHE": {},
        "_AUTHOR_PROFILE_TTL": 6 * 60 * 60,
    }
    exec(code, ns)
    return ns


_NS = _load_namespace()
author_profile = _NS["author_profile"]
_merge_author_profiles = _NS["_merge_author_profiles"]
_fetch_openalex_author_metrics = _NS["_fetch_openalex_author_metrics"]
_AuthorProfileRequest = _NS["_AuthorProfileRequest"]


# --------------------------------------------------------------------------- #
# Offline httpx wiring                                                          #
# --------------------------------------------------------------------------- #

class _MockClientFactory:
    def __init__(self, handler, real_cls):
        self._handler = handler
        self._real_cls = real_cls

    def __call__(self, *args, **kwargs):
        kwargs.pop("timeout", None)
        return self._real_cls(transport=httpx.MockTransport(self._handler))


class _PatchAsyncClient:
    def __init__(self, handler):
        self._handler = handler
        self._orig = None

    def __enter__(self):
        self._orig = httpx.AsyncClient
        httpx.AsyncClient = _MockClientFactory(self._handler, self._orig)
        return self

    def __exit__(self, *exc):
        httpx.AsyncClient = self._orig
        return False


_USER = object()

S2_AUTHOR = {
    "name": "Geoffrey Hinton",
    "affiliations": ["University of Toronto"],
    "paperCount": 500,
    "citationCount": 700000,
    "hIndex": 137,
    "homepage": "https://example.org/hinton",
    "papers": [
        {"title": "Deep Learning", "year": 2015},
        {"title": "Dropout", "year": 2014},
    ],
}

OPENALEX_AUTHOR = {
    "id": "https://openalex.org/A555",
    "display_name": "Geoffrey E. Hinton",
    "works_count": 611,
    "cited_by_count": 812345,
    "orcid": "https://orcid.org/0000-0002-1825-0097",
    "summary_stats": {"h_index": 141, "i10_index": 300},
    "last_known_institutions": [{"display_name": "Google"}],
}


def _handler(*, s2=S2_AUTHOR, openalex=OPENALEX_AUTHOR, s2_status=200, oa_status=200, calls=None):
    def handle(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if calls is not None:
            calls.append(str(request.url))
        if "semanticscholar" in host:
            if s2_status != 200:
                return httpx.Response(s2_status, json={})
            return httpx.Response(200, json=s2)
        if "openalex" in host:
            if oa_status != 200:
                return httpx.Response(oa_status, json={})
            return httpx.Response(200, json=openalex)
        raise AssertionError(f"unexpected host {host}")
    return handle


def _call(author_id=None, openalex_id=None, *, handler, clear=True):
    if clear:
        _NS["_AUTHOR_PROFILE_CACHE"].clear()
    req = _AuthorProfileRequest(author_id=author_id, openalex_id=openalex_id)
    with _PatchAsyncClient(handler):
        return asyncio.run(author_profile(req, current_user=_USER))


# --------------------------------------------------------------------------- #
# The feature: i10-index reaches the hover card                                 #
# --------------------------------------------------------------------------- #

def test_s2_author_with_openalex_id_gains_i10_index():
    """The whole point: an S2-primary author still gets an i10-index, which S2
    itself never publishes."""
    out = _call("1234", "A555", handler=_handler())
    assert out["available"] is True
    assert out["i10Index"] == 300


def test_openalex_only_author_reports_i10_index():
    out = _call(None, "A555", handler=_handler())
    assert out["i10Index"] == 300
    assert out["hIndex"] == 141


def test_s2_numbers_are_not_overwritten_by_openalex():
    """S2 and OpenAlex compute over different corpora. Consulting OpenAlex for
    the i10-index must not silently change the h-index already on screen."""
    out = _call("1234", "A555", handler=_handler())
    assert out["hIndex"] == 137            # S2's, not OpenAlex's 141
    assert out["citationCount"] == 700000  # S2's, not OpenAlex's 812345
    assert out["paperCount"] == 500
    assert out["name"] == "Geoffrey Hinton"


def test_each_metric_records_its_source():
    out = _call("1234", "A555", handler=_handler())
    assert out["metricsSource"] == "semantic_scholar"
    assert out["i10Source"] == "openalex"


def test_no_i10_source_when_no_i10_value():
    """No provenance label without a value to label — nothing invented."""
    oa = dict(OPENALEX_AUTHOR, summary_stats={"h_index": 141})
    out = _call("1234", "A555", handler=_handler(openalex=oa))
    assert out.get("i10Index") is None
    assert out.get("i10Source") is None


def test_openalex_fills_orcid_when_s2_lacks_it():
    out = _call("1234", "A555", handler=_handler())
    assert out["orcid"] == "0000-0002-1825-0097"


def test_s2_papers_survive_the_merge():
    out = _call("1234", "A555", handler=_handler())
    assert [p["title"] for p in out["papers"]] == ["Deep Learning", "Dropout"]
    assert out["homepage"] == "https://example.org/hinton"


# --------------------------------------------------------------------------- #
# Resilience                                                                    #
# --------------------------------------------------------------------------- #

def test_openalex_failure_keeps_the_s2_profile():
    out = _call("1234", "A555", handler=_handler(oa_status=500))
    assert out["available"] is True
    assert out["hIndex"] == 137
    assert out.get("i10Index") is None


def test_s2_failure_falls_back_to_openalex_including_i10():
    out = _call("1234", "A555", handler=_handler(s2_status=404))
    assert out["available"] is True
    assert out["source"] == "openalex"
    assert out["i10Index"] == 300


def test_both_providers_failing_is_soft():
    out = _call("1234", "A555", handler=_handler(s2_status=500, oa_status=500))
    assert out == {"available": False}


def test_no_ids_returns_unavailable_without_any_http():
    calls = []
    out = _call(None, None, handler=_handler(calls=calls))
    assert out == {"available": False}
    assert calls == []


def test_both_providers_are_queried():
    calls = []
    _call("1234", "A555", handler=_handler(calls=calls))
    assert any("semanticscholar" in u for u in calls)
    assert any("openalex" in u for u in calls)


# --------------------------------------------------------------------------- #
# Caching                                                                       #
# --------------------------------------------------------------------------- #

def test_cache_key_covers_both_ids():
    """The same S2 id asked with and without an OpenAlex id yields different
    payloads (i10 present or not), so a key of just the S2 id would serve the
    wrong one."""
    _NS["_AUTHOR_PROFILE_CACHE"].clear()
    with_oa = _call("1234", "A555", handler=_handler(), clear=False)
    without_oa = _call("1234", None, handler=_handler(), clear=False)
    assert with_oa["i10Index"] == 300
    assert without_oa.get("i10Index") is None


def test_repeat_call_is_served_from_cache():
    _NS["_AUTHOR_PROFILE_CACHE"].clear()
    calls = []
    _call("1234", "A555", handler=_handler(calls=calls), clear=False)
    first = len(calls)
    _call("1234", "A555", handler=_handler(calls=calls), clear=False)
    assert len(calls) == first, "second identical request should not re-hit the network"


# --------------------------------------------------------------------------- #
# Merge unit behaviour                                                          #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("primary,openalex,expected", [
    (None, None, {"available": False}),
    ({"available": True, "hIndex": 3}, None, {"available": True, "hIndex": 3}),
])
def test_merge_edge_cases(primary, openalex, expected):
    assert _merge_author_profiles(primary, openalex) == expected


def test_merge_uses_openalex_when_no_primary():
    oa = {"available": True, "hIndex": 5, "i10Index": 2}
    assert _merge_author_profiles(None, oa) == oa


def test_merge_fills_missing_h_index_and_labels_it():
    primary = {"available": True, "name": "X", "hIndex": None, "metricsSource": None}
    oa = {"available": True, "hIndex": 8, "i10Index": 4}
    merged = _merge_author_profiles(primary, oa)
    assert merged["hIndex"] == 8
    assert merged["metricsSource"] == "openalex"
    assert merged["i10Index"] == 4
    assert merged["i10Source"] == "openalex"


# --------------------------------------------------------------------------- #
# Path parity: the ID-less "Find profile" flow reports the same i10-index       #
# --------------------------------------------------------------------------- #

def test_find_profile_metrics_include_i10():
    """`_fetch_openalex_author_metrics` backs the "Find profile" resolution and
    must share the profile endpoint's extraction, or the two hover paths would
    show different numbers for the same author."""
    with _PatchAsyncClient(_handler()):
        metrics = asyncio.run(_fetch_openalex_author_metrics("A555"))
    assert metrics["i10Index"] == 300
    assert metrics["i10Source"] == "openalex"
    assert metrics["hIndex"] == 141
    assert metrics["orcid"] == "0000-0002-1825-0097"


def test_find_profile_metrics_soft_fail():
    with _PatchAsyncClient(_handler(oa_status=500)):
        assert asyncio.run(_fetch_openalex_author_metrics("A555")) == {}
