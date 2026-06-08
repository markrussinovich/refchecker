"""Integration-style tests for ``/api/papers/similar`` MODE DISPATCH.

The endpoint ``backend.main.find_similar_papers`` routes on
``_SimilarPapersRequest.mode``:

  * ``mode='references' | 'citations' | 'both'`` (+ legacy ``'cites_refs'``)
    -> ``_cites_refs_papers_impl`` — the real OpenAlex bibliography-overlap
    neighbourhood, relation-tagged ('reference' = shares references,
    'citation' = shares citations / co-cited).
  * ``mode='similar'`` -> ``_find_similar_papers_impl`` — the historical
    Semantic-Scholar co-citation pipeline, kept reachable for backward
    compatibility and returned untouched.

``backend.main`` cannot be imported here: it pulls in the full refchecker
stack (pdfplumber, GROBID wrappers) and ``refchecker.utils.error_utils``
uses ``int | str`` union syntax that only parses on Python 3.10+. So
rather than re-implement the dispatch (which could drift from reality),
this test loads the ACTUAL dispatch functions' source out of
``backend/main.py`` via ``ast`` and execs only those into a namespace
wired to the REAL deps-free ``backend.cites_refs.fetch_cites_and_refs``
plus a controllable ``_find_similar_papers_impl`` stand-in. The dispatch
logic under test is the real shipped code; only its heavy collaborators
are swapped for offline doubles.

All OpenAlex traffic goes through a fully offline ``httpx.MockTransport``
(same approach as ``tests/unit/test_cites_refs.py``); no live call is made.
"""

import ast
import asyncio
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from backend.cites_refs import fetch_cites_and_refs, normalize_mode

# --------------------------------------------------------------------------- #
# Load the REAL dispatch functions out of backend/main.py                      #
# --------------------------------------------------------------------------- #

_MAIN_PATH = Path(__file__).resolve().parents[2] / "backend" / "main.py"

# The dispatch surface we want to exercise, in dependency order. Every one of
# these is lifted verbatim from backend/main.py; _find_similar_papers_impl is
# the ONLY collaborator we substitute (it owns the heavy S2/web/LLM pipeline).
_WANTED = [
    "_candidate_key",
    "find_similar_papers",
    "_cites_refs_papers_impl",
    "_shape_cites_refs_candidates",
]


def _load_dispatch_namespace():
    """Exec the real dispatch functions from main.py into an isolated ns.

    Returns a dict you can read the dispatch callables out of. The ns is
    primed with the genuine ``fetch_cites_and_refs`` and stdlib bits the
    functions reference, plus the doubles the dispatch leans on (logger,
    httpx, _find_similar_papers_impl).
    """
    tree = ast.parse(_MAIN_PATH.read_text(), filename=str(_MAIN_PATH))
    wanted = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _WANTED:
            wanted[node.name] = node
    missing = [name for name in _WANTED if name not in wanted]
    assert not missing, f"dispatch functions not found in main.py: {missing}"

    # Strip route decorators (@app.post(...)) — they only register the function
    # with FastAPI; the body logic is what we exercise. Keeping them would try to
    # resolve the undefined `app`. The function bodies are untouched.
    for node in wanted.values():
        node.decorator_list = []

    # Re-emit just the wanted defs as a tiny module so they keep their real
    # bodies (and reference each other) without importing all of main.py.
    module = ast.Module(body=[wanted[name] for name in _WANTED], type_ignores=[])
    ast.fix_missing_locations(module)
    code = compile(module, filename=str(_MAIN_PATH), mode="exec")

    ns = {
        # Real, deps-free collaborators the cites_refs impl calls.
        "fetch_cites_and_refs": fetch_cites_and_refs,
        "_normalize_overlap_mode": normalize_mode,
        # Stdlib the function bodies reference.
        "Optional": __import__("typing").Optional,
        "Dict": __import__("typing").Dict,
        "Any": __import__("typing").Any,
        "List": __import__("typing").List,
        # Doubles for heavy module-level names the bodies touch.
        "logger": _NullLogger(),
        "HTTPException": _FakeHTTPException,
        # Names evaluated at def-time in the find_similar_papers signature
        # (annotations + the Depends(require_user) default). These never run;
        # we pass current_user explicitly when calling.
        "Depends": (lambda dep=None: None),
        "require_user": None,
        "UserInfo": object,
        "_SimilarPapersRequest": object,
    }
    # httpx is imported lazily *inside* the function bodies (`import httpx`),
    # so the real httpx is used; we drive it via a MockTransport-backed client
    # by patching httpx.AsyncClient for the duration of each call (see _Patched).
    exec(code, ns)
    return ns


class _NullLogger:
    def __getattr__(self, _name):
        def _noop(*_a, **_k):
            return None
        return _noop


class _FakeHTTPException(Exception):
    def __init__(self, status_code=400, detail=""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


_NS = _load_dispatch_namespace()
find_similar_papers = _NS["find_similar_papers"]
_candidate_key = _NS["_candidate_key"]


# --------------------------------------------------------------------------- #
# Offline httpx wiring                                                          #
# --------------------------------------------------------------------------- #

class _MockClientFactory:
    """Drop-in for ``httpx.AsyncClient`` that always uses a MockTransport.

    The dispatch impls do ``import httpx`` then ``async with
    httpx.AsyncClient() as client``. We monkeypatch ``httpx.AsyncClient``
    to this factory so those clients are fully offline. ``real_cls`` is the
    genuine class captured BEFORE patching, so we don't recurse.
    """

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


# A lightweight request stand-in matching the attrs the dispatch reads.
class _Req:
    def __init__(self, *, references=None, paper_title=None, paper_id=None, limit=5, mode="both"):
        self.references = references or []
        self.paper_title = paper_title
        self.paper_id = paper_id
        self.limit = limit
        self.mode = mode


_USER = object()  # opaque; only _find_similar_papers_impl would touch it.


# Same dedupe key the live similar-papers path uses (asserted == real one below).
def _ref_candidate_key(title, doi, arxiv):
    if doi:
        return f"doi:{doi.strip().lower()}"
    if arxiv:
        return f"arxiv:{arxiv.strip().lower()}"
    if title:
        norm = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
        return f"title:{norm}"
    return f"ghost:{id(title)}"


# --------------------------------------------------------------------------- #
# OpenAlex mock fixtures (mirrors test_cites_refs.py)                           #
# --------------------------------------------------------------------------- #

SOURCE_WORK = {
    "id": "https://openalex.org/W_SRC",
    "title": "The Source Paper",
    "publication_year": 2020,
    "referenced_works": [
        "https://openalex.org/W_R1",
        "https://openalex.org/W_R2",
    ],
}

# Paper that shares both of the source's references.
SHAREREF = {
    "id": "https://openalex.org/W_SHAREREF",
    "title": "Shares References",
    "publication_year": 2019,
    "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
    "doi": "https://doi.org/10.1/shareref",
}

# A citer of the source whose bibliography co-references W_COCITE.
CITER = {
    "id": "https://openalex.org/W_CITER",
    "referenced_works": [
        "https://openalex.org/W_SRC",
        "https://openalex.org/W_COCITE",
    ],
}
CITER2 = {
    "id": "https://openalex.org/W_CITER2",
    "referenced_works": [
        "https://openalex.org/W_SRC",
        "https://openalex.org/W_COCITE",
    ],
}
COCITE = {
    "id": "https://openalex.org/W_COCITE",
    "title": "Co-cited Work",
    "publication_year": 2017,
    "authorships": [{"author": {"display_name": "Grace Hopper"}}],
    "doi": "https://doi.org/10.2/cocite",
}


def _openalex_handler(request: httpx.Request) -> httpx.Response:
    """Offline OpenAlex for the bibliography-overlap neighbourhood."""
    url = str(request.url)
    qs = parse_qs(urlparse(url).query)
    filt = (qs.get("filter") or [""])[0]

    if "/works/doi:" in url:
        return httpx.Response(200, json=SOURCE_WORK)
    # Shared references: works that also cite the source's references.
    if filt in ("cites:W_R1", "cites:W_R2"):
        return httpx.Response(200, json={"results": [SHAREREF]})
    # Shared citations: the source's citers (with bibliographies).
    if filt == "cites:W_SRC":
        return httpx.Response(200, json={"results": [CITER, CITER2]})
    if filt.startswith("openalex_id:"):
        ids = filt[len("openalex_id:"):].split("|")
        table = {"W_COCITE": COCITE}
        return httpx.Response(200, json={"results": [table[i] for i in ids if i in table]})
    if filt.startswith("title.search:"):
        return httpx.Response(200, json={"results": []})
    return httpx.Response(404, json={"results": []})


def _call(req, *, similar_impl=None, handler=_openalex_handler):
    """Run the real dispatcher with a patched httpx + injected similar impl."""
    # Inject the controllable similar pipeline into the dispatch namespace.
    async def _default_similar(_req, _user):  # pragma: no cover - guard
        raise AssertionError("_find_similar_papers_impl must not run in this mode")

    _NS["_find_similar_papers_impl"] = similar_impl or _default_similar
    with _PatchAsyncClient(handler):
        return asyncio.run(find_similar_papers(req, current_user=_USER))


# --------------------------------------------------------------------------- #
# Tests                                                                         #
# --------------------------------------------------------------------------- #

def test_dispatch_key_matches_cites_refs_helper_key():
    """The dispatch's _candidate_key must agree with the cites_refs dedupe key
    used in tests/unit/test_cites_refs.py — they share the dedupe contract."""
    samples = [
        ("Some Title", "10.5/DUP", None),
        ("Other Title", None, "2304.01234"),
        ("Title Only Paper", None, None),
    ]
    for title, doi, arxiv in samples:
        assert _candidate_key(title, doi, arxiv) == _ref_candidate_key(title, doi, arxiv)


def test_both_mode_returns_relation_tagged_overlap():
    """mode='both' -> real OpenAlex overlap, every row relation-tagged."""
    req = _Req(paper_id="10.1234/source", paper_title="The Source Paper", limit=5, mode="both")
    out = _call(req)

    assert out["mode"] == "both"
    assert out["source_work"] == "W_SRC"
    cands = out["candidates"]
    assert cands, "both should surface the real overlap neighbourhood"

    relations = {c["relation"] for c in cands}
    assert relations == {"reference", "citation"}
    # Every candidate carries a relation tag (the whole point of this mode).
    assert all(c.get("relation") in {"reference", "citation"} for c in cands)
    # Rows are shaped onto the Similar-Papers UI row contract.
    for c in cands:
        assert "title" in c and "sources" in c and c["sources"] == ["openalex"]

    titles = {c["title"] for c in cands}
    assert "Shares References" in titles   # shared-references row
    assert "Co-cited Work" in titles       # shared-citations row
    # source_counts tallies by relation.
    assert out["source_counts"].get("reference") == 1
    assert out["source_counts"].get("citation") == 1
    # The overlap count that earned each row a place is carried through.
    shareref = next(c for c in cands if c["title"] == "Shares References")
    assert shareref["shared_with_source"] == 2  # shares both source refs
    cocite = next(c for c in cands if c["title"] == "Co-cited Work")
    assert cocite["shared_with_source"] == 2    # co-cited by 2 citers


def test_references_mode_only_shared_reference_rows():
    """mode='references' -> only shared-references rows (relation='reference')."""
    req = _Req(paper_id="10.1234/source", limit=5, mode="references")
    out = _call(req)
    assert out["mode"] == "references"
    assert {c["relation"] for c in out["candidates"]} == {"reference"}


def test_citations_mode_only_shared_citation_rows():
    """mode='citations' -> only shared-citations rows (relation='citation')."""
    req = _Req(paper_id="10.1234/source", limit=5, mode="citations")
    out = _call(req)
    assert out["mode"] == "citations"
    assert {c["relation"] for c in out["candidates"]} == {"citation"}


def test_legacy_cites_refs_mode_maps_to_both():
    """The legacy 'cites_refs' alias resolves to the 'both' overlap union."""
    req = _Req(paper_id="10.1234/source", limit=5, mode="cites_refs")
    out = _call(req)
    assert out["mode"] == "both"
    assert {c["relation"] for c in out["candidates"]} == {"reference", "citation"}


def test_overlap_mode_no_duplicate_candidate_key():
    """A work surfacing as both a shared-reference and a co-citation collapses."""
    dup = {
        "id": "https://openalex.org/W_DUP",
        "title": "Appears Twice",
        "publication_year": 2019,
        "authorships": [],
        "doi": "https://doi.org/10.5/dup",
    }
    dup_citer = {
        "id": "https://openalex.org/W_DUPCITER",
        "referenced_works": [
            "https://openalex.org/W_SRC2",
            "https://openalex.org/W_DUP",
        ],
    }

    def handler(request):
        url = str(request.url)
        qs = parse_qs(urlparse(url).query)
        filt = (qs.get("filter") or [""])[0]
        if "/works/doi:" in url:
            return httpx.Response(200, json={
                "id": "https://openalex.org/W_SRC2",
                "title": "Source Two",
                "referenced_works": ["https://openalex.org/W_REF"],
            })
        if filt == "cites:W_REF":
            return httpx.Response(200, json={"results": [dup]})
        if filt == "cites:W_SRC2":
            return httpx.Response(200, json={"results": [dup_citer]})
        if filt.startswith("openalex_id:"):
            return httpx.Response(200, json={"results": [dup]})
        return httpx.Response(200, json={"results": []})

    req = _Req(paper_id="10.5/src2", limit=5, mode="both")
    out = _call(req, handler=handler)

    keys = [_candidate_key(c.get("title"), c.get("doi"), c.get("arxiv_id")) for c in out["candidates"]]
    assert len(keys) == len(set(keys)), f"duplicate candidate_key in overlap modes: {keys}"
    assert keys.count("doi:10.5/dup") == 1


def test_similar_legacy_path_is_guarded_and_unchanged():
    """mode='similar' falls through to the historical pipeline untouched — the
    dispatcher returns its result verbatim and never touches the overlap path."""
    sentinel = {
        "source_paper": "The Source Paper",
        "candidates": [{"title": "Untouched Row", "doi": "10.0/keep"}],
        "source_counts": {"semantic_scholar": 1},
        "total_candidates": 1,
    }

    async def _similar_impl(req, user):
        assert user is _USER
        return sentinel

    out = _call(_Req(paper_id="10.1234/source", mode="similar", limit=5), similar_impl=_similar_impl)
    assert out is sentinel  # returned verbatim, no re-shaping
    assert "mode" not in out  # the legacy path doesn't stamp a mode key


def test_dispatch_swallows_errors_into_safe_envelope():
    """Any impl error is caught and returned as an empty, non-crashing envelope
    (the dispatcher's try/except contract) — never a 500 bubbling to the user."""

    async def _boom(req, user):
        raise RuntimeError("pipeline exploded")

    out = _call(_Req(paper_title="Boom Paper", mode="similar"), similar_impl=_boom)
    assert out["candidates"] == []
    assert out["source_paper"] == "Boom Paper"
    assert "error" in out and "exploded" in out["error"]
