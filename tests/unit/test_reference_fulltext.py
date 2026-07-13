"""R43 — per-reference full-text retrieval for grounded chat.

Exercises ``refchecker.utils.reference_fulltext`` with the network + PyMuPDF
layers monkeypatched (no real downloads / no fitz needed) and asserts the
honesty contract:

  * OA hit  → ``(full_text, 'pdf')`` — chat grounds in the fetched document.
  * OA miss → ``(None, 'tldr')``     — the FE keeps the TL;DR disclaimer.
  * Soft-fail: a download / extraction / resolver error never raises; it falls
    back to ``(None, 'tldr')``.
  * Cached per identity (arXiv id / DOI / title) with a negative cache for
    misses, so a re-opened chat doesn't re-fetch.
"""

import pytest

from refchecker.utils import reference_fulltext as rf


@pytest.fixture(autouse=True)
def _clear_cache():
    rf.clear_cache()
    yield
    rf.clear_cache()


# --------------------------------------------------------------------------- #
# Identity / DOI helpers                                                       #
# --------------------------------------------------------------------------- #

def test_identity_key_priority_and_normalization():
    # arXiv wins over DOI/title.
    assert rf._identity_key({"arxiv_id": "2310.06825", "doi": "10.1/x", "title": "T"}) == "arxiv:2310.06825"
    # DOI is normalised (resolver prefix stripped, lowercased).
    assert rf._identity_key({"doi": "https://doi.org/10.1145/AbC"}) == "doi:10.1145/abc"
    # Title fallback is lowercased.
    assert rf._identity_key({"title": "Attention Is All You Need"}) == "title:attention is all you need"
    # No real identity → None (caller won't attempt retrieval).
    assert rf._identity_key({}) is None
    assert rf._identity_key({"doi": "not-a-doi"}) is None


def test_clean_doi_rejects_non_doi():
    assert rf._clean_doi("10.1145/3292500") == "10.1145/3292500"
    assert rf._clean_doi("doi:10.5555/Foo/Bar") == "10.5555/foo/bar"
    assert rf._clean_doi("https://example.com/x") is None
    assert rf._clean_doi(None) is None


# --------------------------------------------------------------------------- #
# OA hit → full-text grounding                                                 #
# --------------------------------------------------------------------------- #

def test_oa_hit_returns_full_text_and_pdf_source(monkeypatch):
    full = "F" * (rf._MIN_FULLTEXT_CHARS + 100)

    def fake_resolve(reference):
        return "https://arxiv.org/pdf/2310.06825.pdf"

    def fake_dl(url, **kwargs):
        return b"%PDF-fake-bytes"

    def fake_extract(data):
        return full

    monkeypatch.setattr(rf, "_resolve_oa_pdf_url", fake_resolve)
    # Patch the download + extraction at the seam so no network / fitz needed.
    monkeypatch.setattr("refchecker.utils.url_utils.download_pdf_bytes", fake_dl)
    monkeypatch.setattr(rf, "_extract_pdf_text", fake_extract)

    text, source = rf.get_reference_fulltext({"arxiv_id": "2310.06825"})
    assert source == "pdf"
    assert text == full


def test_fulltext_capped_to_chat_grounding_budget(monkeypatch):
    # In ref-mode the fetched full text rides into the chat as a message-history
    # turn, so the backend's MAX_GROUNDING_CHARS guard never truncates it — this
    # cap is the REAL bound. It must stay in lockstep with the chat budget so an
    # oversized reference body can't overflow the model context / inflate cost.
    huge = "F" * (rf._MAX_FULLTEXT_CHARS * 3)

    monkeypatch.setattr(rf, "_resolve_oa_pdf_url", lambda r: "https://host/p.pdf")
    monkeypatch.setattr("refchecker.utils.url_utils.download_pdf_bytes", lambda url, **k: b"%PDF")
    monkeypatch.setattr(rf, "_extract_pdf_text", lambda data: huge)

    text, source = rf.get_reference_fulltext({"arxiv_id": "2310.06825"})
    assert source == "pdf"
    assert text is not None and len(text) == rf._MAX_FULLTEXT_CHARS

    # The cap must match the backend chat grounding budget it is documented to
    # mirror, so the two bounds can't silently drift apart. Skip cleanly when
    # the (desktop-only) backend package isn't present — this util ships in the
    # core library independently of the FastAPI backend.
    article_chat = pytest.importorskip("backend.article_chat")
    assert rf._MAX_FULLTEXT_CHARS == article_chat.MAX_GROUNDING_CHARS


def test_arxiv_reference_resolves_pdf_url_without_network():
    url = rf._resolve_oa_pdf_url({"arxiv_id": "2310.06825"})
    assert url and "2310.06825" in url and url.endswith(".pdf")


def test_enrichment_oa_pdf_url_short_circuits_resolution():
    ref = {"doi": "10.1/x", "enrichment": {"oa_pdf_url": "https://host/paper.pdf"}}
    assert rf._resolve_oa_pdf_url(ref) == "https://host/paper.pdf"


# --------------------------------------------------------------------------- #
# OA miss → tldr fallback                                                      #
# --------------------------------------------------------------------------- #

def test_no_oa_url_returns_tldr(monkeypatch):
    monkeypatch.setattr(rf, "_resolve_oa_pdf_url", lambda r: None)
    text, source = rf.get_reference_fulltext({"doi": "10.1145/3292500"})
    assert text is None
    assert source == "tldr"


def test_too_short_extraction_is_a_miss(monkeypatch):
    monkeypatch.setattr(rf, "_resolve_oa_pdf_url", lambda r: "https://host/p.pdf")
    monkeypatch.setattr("refchecker.utils.url_utils.download_pdf_bytes", lambda url, **k: b"%PDF")
    # A near-empty extraction (cover page / paywall stub) must NOT be trusted.
    monkeypatch.setattr(rf, "_extract_pdf_text", lambda data: "tiny")
    text, source = rf.get_reference_fulltext({"doi": "10.1145/3292500"})
    assert text is None
    assert source == "tldr"


def test_no_identity_returns_tldr():
    text, source = rf.get_reference_fulltext({})
    assert text is None
    assert source == "tldr"


def test_download_error_soft_fails(monkeypatch):
    monkeypatch.setattr(rf, "_resolve_oa_pdf_url", lambda r: "https://host/p.pdf")

    def boom(url, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("refchecker.utils.url_utils.download_pdf_bytes", boom)
    # Must not raise — soft-fails to the TL;DR fallback.
    text, source = rf.get_reference_fulltext({"doi": "10.1145/3292500"})
    assert text is None
    assert source == "tldr"


# --------------------------------------------------------------------------- #
# Caching (positive + negative)                                               #
# --------------------------------------------------------------------------- #

def test_positive_cache_avoids_refetch(monkeypatch):
    full = "G" * (rf._MIN_FULLTEXT_CHARS + 10)
    calls = {"n": 0}

    def fake_dl(url, **kwargs):
        calls["n"] += 1
        return b"%PDF"

    monkeypatch.setattr(rf, "_resolve_oa_pdf_url", lambda r: "https://host/p.pdf")
    monkeypatch.setattr("refchecker.utils.url_utils.download_pdf_bytes", fake_dl)
    monkeypatch.setattr(rf, "_extract_pdf_text", lambda data: full)

    ref = {"doi": "10.1145/3292500"}
    t1, s1 = rf.get_reference_fulltext(ref)
    t2, s2 = rf.get_reference_fulltext(ref)
    assert (t1, s1) == (full, "pdf")
    assert (t2, s2) == (full, "pdf")
    assert calls["n"] == 1  # second call served from cache


def test_negative_cache_avoids_refetch(monkeypatch):
    resolves = {"n": 0}

    def fake_resolve(reference):
        resolves["n"] += 1
        return None

    monkeypatch.setattr(rf, "_resolve_oa_pdf_url", fake_resolve)
    ref = {"doi": "10.1145/3292500"}
    assert rf.get_reference_fulltext(ref) == (None, "tldr")
    assert rf.get_reference_fulltext(ref) == (None, "tldr")
    assert resolves["n"] == 1  # miss is cached; not re-resolved
