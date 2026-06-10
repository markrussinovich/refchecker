"""R10 (A3) — ID-less author resolution by name + paper title/year.

Exercises ``backend.main.author_find`` (POST /api/authors/find): given a bare
author name PLUS the citing paper's title (and optional year), it resolves a
SINGLE high-confidence OpenAlex author id — but ONLY when that author actually
appears on a work whose title matches the supplied one. Otherwise it ABSTAINS
({available: False}). The whole point of R10 is *non-fabrication*: a wrong
author profile is worse than none.

``backend.main`` cannot be imported wholesale here (it pulls in the full
refchecker stack + Python-3.10-only union syntax), so — exactly like
``tests/unit/test_similar_mode_dispatch.py`` — we load ONLY the author-find
functions out of ``backend/main.py`` via ``ast`` and exec them into an isolated
namespace wired to an offline ``httpx.MockTransport``. The logic under test is
the real shipped code; only its OpenAlex HTTP calls are doubled.
"""

import ast
import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

_MAIN_PATH = Path(__file__).resolve().parents[2] / "backend" / "main.py"

# The author-find surface lifted verbatim from main.py, in dependency order.
_WANTED = [
    "_normalize_person_name",
    "_name_tokens",
    "_author_corroborated_on_work",
    "_fetch_openalex_author_metrics",
    "author_find",
]


class _NullLogger:
    def __getattr__(self, _name):
        def _noop(*_a, **_k):
            return None
        return _noop


def _load_namespace():
    tree = ast.parse(_MAIN_PATH.read_text(), filename=str(_MAIN_PATH))
    wanted = {}
    pydantic_models = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _WANTED:
            wanted[node.name] = node
        # Pull the request model so we can build a real pydantic instance.
        if isinstance(node, ast.ClassDef) and node.name == "_AuthorFindRequest":
            pydantic_models[node.name] = node
    missing = [n for n in _WANTED if n not in wanted]
    assert not missing, f"author-find functions not found in main.py: {missing}"
    assert "_AuthorFindRequest" in pydantic_models, "_AuthorFindRequest model not found"

    # Strip route decorators (@app.post(...)) — they only register with FastAPI.
    for node in wanted.values():
        node.decorator_list = []

    body = [pydantic_models["_AuthorFindRequest"]] + [wanted[n] for n in _WANTED]
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    code = compile(module, filename=str(_MAIN_PATH), mode="exec")

    from typing import Any, Dict, List, Optional
    from pydantic import BaseModel
    import re as _re

    ns = {
        "Optional": Optional, "Dict": Dict, "Any": Any, "List": List,
        "BaseModel": BaseModel,
        "re": _re,
        "logger": _NullLogger(),
        # Eval-at-def-time names in the endpoint signature; never invoked because
        # we call author_find(req, current_user=...) directly.
        "Depends": (lambda dep=None: None),
        "require_user": None,
        "UserInfo": object,
        "HTTPException": Exception,
        # Module-level state the endpoint reads (assigned at import time in
        # main.py; re-seeded here so the exec'd functions have them).
        "_AUTHOR_FIND_CACHE": {},
        "_AUTHOR_FIND_TTL": 6 * 60 * 60,
    }
    exec(code, ns)
    return ns


_NS = _load_namespace()
author_find = _NS["author_find"]
_AuthorFindRequest = _NS["_AuthorFindRequest"]
_normalize_person_name = _NS["_normalize_person_name"]
_author_corroborated_on_work = _NS["_author_corroborated_on_work"]


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


def _call(name=None, title=None, year=None, *, handler):
    # Fresh cache per call so cross-test bleed can't mask a real failure.
    _NS["_AUTHOR_FIND_CACHE"].clear()
    req = _AuthorFindRequest(name=name, title=title, year=year)
    with _PatchAsyncClient(handler):
        return asyncio.run(author_find(req, current_user=_USER))


# --------------------------------------------------------------------------- #
# OpenAlex fixtures                                                             #
# --------------------------------------------------------------------------- #

TITLE = "A Comparison of Treatment Effects in Endocrine Disorders"

# The matching work lists exactly ONE author whose surname corroborates the
# query name ("Jane Q. Researcher") -> a confident, single match.
WORK_CONFIDENT = {
    "id": "https://openalex.org/W100",
    "title": TITLE,
    "publication_year": 2018,
    "authorships": [
        {"author": {"id": "https://openalex.org/A111", "display_name": "Jane Q. Researcher"}},
        {"author": {"id": "https://openalex.org/A222", "display_name": "Carlos Mendez"}},
    ],
}

# Same title, but TWO same-surname authors -> ambiguous -> ABSTAIN.
WORK_AMBIGUOUS = {
    "id": "https://openalex.org/W200",
    "title": TITLE,
    "publication_year": 2018,
    "authorships": [
        {"author": {"id": "https://openalex.org/A301", "display_name": "Jane Researcher"}},
        {"author": {"id": "https://openalex.org/A302", "display_name": "Mark Researcher"}},
    ],
}

# A work that does NOT list the queried author at all -> no corroboration.
WORK_NO_AUTHOR = {
    "id": "https://openalex.org/W300",
    "title": TITLE,
    "publication_year": 2018,
    "authorships": [
        {"author": {"id": "https://openalex.org/A401", "display_name": "Someone Else"}},
        {"author": {"id": "https://openalex.org/A402", "display_name": "Another Person"}},
    ],
}

AUTHOR_A111 = {
    "id": "https://openalex.org/A111",
    "display_name": "Jane Q. Researcher",
    "works_count": 42,
    "cited_by_count": 1500,
    "summary_stats": {"h_index": 21},
    "ids": {"orcid": "https://orcid.org/0000-0002-1825-0097"},
    "last_known_institutions": [{"display_name": "Institute of Things"}],
}


def _make_handler(work):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/works" in url and "/works/" not in url:
            qs = parse_qs(urlparse(url).query)
            filt = (qs.get("filter") or [""])[0]
            assert "title.search:" in filt
            return httpx.Response(200, json={"results": [work] if work else []})
        if "/authors/A111" in url:
            return httpx.Response(200, json=AUTHOR_A111)
        if "/authors/" in url:
            return httpx.Response(200, json={})
        return httpx.Response(404, json={})
    return handler


# --------------------------------------------------------------------------- #
# Tests — corroboration helper                                                 #
# --------------------------------------------------------------------------- #

def test_corroboration_matches_on_surname_plus_token_overlap():
    # Same person, accents + initials differ -> still corroborates.
    assert _author_corroborated_on_work("Jane Q. Researcher", ["Jane Q. Researcher"])
    assert _author_corroborated_on_work("J. Researcher", ["Jane Researcher"])
    # Different surname -> no match (real-data gate).
    assert _author_corroborated_on_work("Jane Researcher", ["Carlos Mendez"]) is None
    # Empty / lone-initial only -> no spurious match.
    assert _author_corroborated_on_work("J.", ["Jane Researcher"]) is None


def test_normalize_strips_diacritics_and_punctuation():
    assert _normalize_person_name("Bössuyt,") == "bossuyt"
    assert _normalize_person_name("Jane  Q. Researcher") == "jane q researcher"


# --------------------------------------------------------------------------- #
# Tests — endpoint behaviour                                                    #
# --------------------------------------------------------------------------- #

def test_confident_single_match_returns_id_and_metrics():
    out = _call(name="Jane Q. Researcher", title=TITLE, year=2018,
                handler=_make_handler(WORK_CONFIDENT))
    assert out["available"] is True
    assert out["openalex_id"] == "A111"
    assert out["source"] == "openalex"
    assert out["matched_work_title"] == TITLE
    # Hydrated real metrics from the OpenAlex author record.
    assert out["hIndex"] == 21
    assert out["citationCount"] == 1500
    assert out["paperCount"] == 42
    assert out["orcid"] == "0000-0002-1825-0097"


def test_ambiguous_same_surname_authors_abstains():
    """Two same-surname authors on the matching work -> we cannot pick one
    confidently, so we return empty rather than guess."""
    out = _call(name="Jane Researcher", title=TITLE, year=2018,
                handler=_make_handler(WORK_AMBIGUOUS))
    assert out["available"] is False
    assert out.get("reason") == "no confident match"
    assert "openalex_id" not in out


def test_work_without_the_author_abstains():
    """The title matches a real work, but that work doesn't list the queried
    author -> no corroboration -> empty."""
    out = _call(name="Jane Researcher", title=TITLE, year=2018,
                handler=_make_handler(WORK_NO_AUTHOR))
    assert out["available"] is False
    assert out.get("reason") == "no confident match"


def test_no_matching_work_abstains():
    out = _call(name="Jane Researcher", title="A Title That Matches Nothing",
                handler=_make_handler(None))
    assert out["available"] is False
    assert out.get("reason") == "no confident match"


def test_missing_title_refuses_without_calling_openalex():
    """No corroboration anchor (no title) -> never search, never guess."""
    called = {"n": 0}

    def handler(request):
        called["n"] += 1
        return httpx.Response(200, json={"results": []})

    out = _call(name="Jane Researcher", title=None, handler=handler)
    assert out["available"] is False
    assert out.get("reason") == "no confident match"
    assert called["n"] == 0, "must not hit OpenAlex without a title anchor"
