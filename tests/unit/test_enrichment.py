"""Unit tests for reference enrichment (build_enrichment).

Loaded directly from the source file so the suite runs without the heavy
``refchecker`` package __init__ (which pulls tqdm etc.) — the module itself is
pure stdlib.
"""

import importlib.util
import pathlib

_ENRICH_PATH = pathlib.Path(__file__).resolve().parents[2] / "src" / "refchecker" / "utils" / "enrichment.py"
_spec = importlib.util.spec_from_file_location("rc_enrichment_under_test", _ENRICH_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_enrichment = _mod.build_enrichment


# --------------------------------------------------------------------------- #
# New article-intelligence fields (abstract / tldr / oa_pdf_url / is_preprint)  #
# --------------------------------------------------------------------------- #

def test_build_enrichment_emits_tldr_from_s2():
    e = build_enrichment({"tldr": {"text": "Key finding X"}})
    assert e["tldr"] == "Key finding X"
    # Absent/null tldr -> the KEY is absent (not '' / None).
    assert "tldr" not in build_enrichment({"title": "x"})
    assert "tldr" not in build_enrichment({"tldr": {"text": None}})


def test_build_enrichment_abstract_prefers_s2_string_then_reconstructs_openalex():
    # S2/Crossref plain string is used verbatim.
    assert build_enrichment({"abstract": "Plain abstract."})["abstract"] == "Plain abstract."
    # When absent, OpenAlex inverted index is reconstructed in position order.
    inv = {"Deep": [0], "learning": [1], "works": [2]}
    assert build_enrichment({"abstract_inverted_index": inv})["abstract"] == "Deep learning works"
    # Duplicate positions / gaps don't scramble (word repeated at each index).
    inv2 = {"the": [0, 2], "cat": [1], "sat": [3]}
    assert build_enrichment({"abstract_inverted_index": inv2})["abstract"] == "the cat the sat"
    # No abstract anywhere -> key absent.
    assert "abstract" not in build_enrichment({"title": "x"})


def test_build_enrichment_crossref_abstract_strips_jats():
    e = build_enrichment({"abstract": "<jats:p>Hello <jats:italic>world</jats:italic></jats:p>"})
    assert e["abstract"] == "Hello world"


def test_build_enrichment_oa_pdf_url_waterfall():
    # S2 wins.
    e = build_enrichment({
        "openAccessPdf": {"url": "https://s2.example/p.pdf"},
        "open_access": {"oa_url": "https://oa.example/p"},
    })
    assert e["oa_pdf_url"] == "https://s2.example/p.pdf"
    assert e["links"]["oa_pdf"] == "https://s2.example/p.pdf"
    # OpenAlex oa_url next.
    assert build_enrichment({"open_access": {"oa_url": "https://oa.example/p"}})["oa_pdf_url"] == "https://oa.example/p"
    # primary_location.pdf_url last.
    assert build_enrichment({"primary_location": {"pdf_url": "https://pl.example/p.pdf"}})["oa_pdf_url"] == "https://pl.example/p.pdf"
    # None present -> key absent.
    assert "oa_pdf_url" not in build_enrichment({"title": "x"})


def test_build_enrichment_is_preprint():
    assert build_enrichment({"type": "preprint"}).get("is_preprint") is True
    assert build_enrichment({"type": "posted-content"}).get("is_preprint") is True
    # Real journal article -> key absent (absence != False).
    assert "is_preprint" not in build_enrichment({"type": "journal-article"})


def test_build_enrichment_empty_input_returns_empty_dict():
    assert build_enrichment({}) == {}
    assert build_enrichment(None) == {}
    assert build_enrichment("not a dict") == {}


# --------------------------------------------------------------------------- #
# Existing normalized fields keep working (regression guard for the widening)   #
# --------------------------------------------------------------------------- #

def test_build_enrichment_existing_counts_still_normalized():
    e = build_enrichment({"citationCount": 65, "referenceCount": 30, "type": "journal-article"})
    assert e["cited_by_count"] == 65
    assert e["reference_count"] == 30
    assert e["publication_type"] == "journal-article"


def test_build_enrichment_funders_from_grants():
    e = build_enrichment({"grants": [{"funder_display_name": "NIH"}, {"funder_display_name": "NSF"}]})
    assert e["has_funding"] is True
    assert e["funders"] == ["NIH", "NSF"]


def test_build_enrichment_funders_from_crossref_s2_funders_list():
    # Crossref/S2-shaped `funder[]`/`funders[]` (name key, or plain strings).
    e = build_enrichment({"funder": [{"name": "Wellcome Trust"}, {"name": "ERC"}]})
    assert e["has_funding"] is True
    assert e["funders"] == ["Wellcome Trust", "ERC"]
    e2 = build_enrichment({"funders": ["DFG", "ANR"]})
    assert e2["funders"] == ["DFG", "ANR"]
    # No funder named anywhere -> keys absent (absence != "no funding").
    assert "has_funding" not in build_enrichment({"title": "x"})


# --------------------------------------------------------------------------- #
# Regression: a full Semantic-Scholar-shaped verified_data (exactly what the    #
# S2 checker now returns once a matched-but-sparse paper is topped up from the  #
# /paper/{paperId} record) yields abstract / tldr / cited_by_count /            #
# reference_count on the reference card. This is the bug the fix targets:       #
# previously only externalIds survived into verified_data, so the card showed   #
# the link chips (PMID/LibKey/WorldCat) but no Abstract / Claim / counts.       #
# --------------------------------------------------------------------------- #

def test_build_enrichment_full_s2_shaped_payload_yields_rich_fields():
    s2_verified_data = {
        "paperId": "abc123def456",
        "title": "Attention Is All You Need",
        "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.",
        "tldr": {"model": "tldr@v2.0.0", "text": "Introduces the Transformer, a model based solely on attention."},
        "citationCount": 95000,
        "referenceCount": 38,
        "year": 2017,
        "venue": "NeurIPS",
        "publicationTypes": ["JournalArticle", "Conference"],
        "publicationDate": "2017-06-12",
        "fieldsOfStudy": ["Computer Science"],
        "externalIds": {
            "DOI": "10.5555/3295222.3295349",
            "ArXiv": "1706.03762",
            "PubMed": "12345678",
            "MAG": "2963403868",
        },
        "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762.pdf"},
        "isOpenAccess": True,
        "_matched_database": "Semantic Scholar",
    }
    e = build_enrichment(s2_verified_data)

    # The fields that were silently dropped before the fix.
    assert e["abstract"].startswith("The dominant sequence transduction models")
    assert e["tldr"] == "Introduces the Transformer, a model based solely on attention."
    assert e["cited_by_count"] == 95000
    assert e["reference_count"] == 38

    # And the link IDs that always worked still do (regression guard).
    assert e["pubmed_id"] == "12345678"
    assert e["mag_id"] == "2963403868"
    assert e["links"]["doi"] == "10.5555/3295222.3295349"
    assert e["source_label"] == "Semantic Scholar"
    # Field-of-study + OA PDF surface from the S2 shape too.
    assert e["fields_of_study"] == ["Computer Science"]
    assert e["oa_pdf_url"] == "https://arxiv.org/pdf/1706.03762.pdf"


def test_build_enrichment_tldr_accepts_plain_string():
    # Flattened S2 tldr (plain string) is accepted, same as the nested dict.
    assert build_enrichment({"tldr": "A flat claim string."})["tldr"] == "A flat claim string."
    # Nested form still works.
    assert build_enrichment({"tldr": {"text": "Nested claim."}})["tldr"] == "Nested claim."
    # Empty/blank string -> key absent.
    assert "tldr" not in build_enrichment({"tldr": "   "})


# --------------------------------------------------------------------------- #
# Cross-source backfill (R21 / R22) — backfill_enrichment                       #
#                                                                             #
# All tests are network-free: the per-DOI gather is stubbed, so no real HTTP   #
# is issued. They lock the never-overwrite / never-fabricate / soft-fail       #
# contract and the "skip when already rich" short-circuit.                     #
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402

backfill_enrichment = _mod.backfill_enrichment


@pytest.fixture(autouse=True)
def _clear_backfill_cache():
    """Each backfill test starts with an empty per-DOI cache."""
    _mod._BACKFILL_CACHE.clear()
    yield
    _mod._BACKFILL_CACHE.clear()


def _stub_gather(monkeypatch, fields):
    """Make _gather_backfill_fields return `fields` for any DOI without
    touching the network (so no real OpenAlex/Crossref/S2 call fires)."""
    calls = {"n": 0}

    def fake_gather(doi):
        calls["n"] += 1
        return dict(fields)

    monkeypatch.setattr(_mod, "_gather_backfill_fields", fake_gather)
    return calls


def test_backfill_non_dict_input_returned_unchanged(monkeypatch):
    _stub_gather(monkeypatch, {"cited_by_count": 5})
    assert backfill_enrichment(None) is None
    assert backfill_enrichment("nope") == "nope"


def test_backfill_merges_only_when_missing(monkeypatch):
    # A non-S2 winner (DBLP-shaped) with a DOI but no counts/abstract/tldr.
    vd = {"doi": "10.1109/ABC.2021.12345", "source": "DBLP", "title": "Paper"}
    _stub_gather(monkeypatch, {
        "cited_by_count": 182,
        "referenced_works": ["W1", "W2", "W3"],
        "abstract": "A real abstract.",
        "tldr": {"text": "A real claim."},
        "grants": [{"funder_display_name": "NIH"}],
    })
    out = backfill_enrichment(vd, {"doi": "10.1109/ABC.2021.12345"})
    # Mutated in place AND returned (caller convenience).
    assert out is vd
    e = build_enrichment(out)
    assert e["cited_by_count"] == 182
    assert e["reference_count"] == 3
    assert e["abstract"] == "A real abstract."
    assert e["tldr"] == "A real claim."
    assert e["has_funding"] is True and e["funders"] == ["NIH"]


def test_backfill_never_overwrites_existing_real_values(monkeypatch):
    # Winner carries a real count but NO rich field (so backfill DOES run — the
    # rich family is empty). The backfill source returns a DIFFERENT count plus
    # a genuinely-missing referenceCount + abstract: the existing real count
    # must survive untouched, the missing fields must be filled.
    vd = {
        "doi": "10.1/x",
        "cited_by_count": 10,   # real existing count — must NOT be overwritten
    }
    _stub_gather(monkeypatch, {
        "cited_by_count": 999,            # different value — must be ignored
        "abstract": "Backfilled abstract.",  # missing → should be added
        "referenceCount": 42,             # missing → should be added
    })
    backfill_enrichment(vd)
    assert vd["cited_by_count"] == 10               # not overwritten
    assert vd["abstract"] == "Backfilled abstract."  # missing → backfilled
    assert vd["referenceCount"] == 42              # missing → backfilled
    e = build_enrichment(vd)
    assert e["cited_by_count"] == 10
    assert e["reference_count"] == 42
    assert e["abstract"] == "Backfilled abstract."


def test_backfill_does_not_overwrite_existing_rich_when_count_missing(monkeypatch):
    # Symmetric guard: a winner with a real abstract/tldr but no count. Backfill
    # runs (count family empty) and must NOT clobber the existing rich values.
    vd = {
        "doi": "10.1/y",
        "abstract": "Original abstract.",
        "tldr": "Original claim.",
    }
    _stub_gather(monkeypatch, {
        "cited_by_count": 77,                 # missing → should be added
        "abstract": "Backfilled abstract.",   # existing → must be ignored
        "tldr": {"text": "Backfilled claim."},  # existing → must be ignored
    })
    backfill_enrichment(vd)
    assert vd["cited_by_count"] == 77             # missing → backfilled
    assert vd["abstract"] == "Original abstract."  # not overwritten
    assert vd["tldr"] == "Original claim."        # not overwritten


def test_backfill_skips_network_when_already_rich(monkeypatch):
    # Payload already has BOTH a count AND a rich field → no DOI lookup at all.
    calls = _stub_gather(monkeypatch, {"cited_by_count": 5})
    vd = {"doi": "10.1/x", "citationCount": 7, "abstract": "Has one."}
    backfill_enrichment(vd)
    assert calls["n"] == 0          # gather never called
    assert vd["citationCount"] == 7  # untouched


def test_backfill_no_doi_does_nothing(monkeypatch):
    calls = _stub_gather(monkeypatch, {"cited_by_count": 5})
    vd = {"source": "DBLP", "title": "No DOI here"}
    backfill_enrichment(vd, {"title": "No DOI here"})
    assert calls["n"] == 0
    assert "cited_by_count" not in vd


def test_backfill_resolves_doi_from_reference_when_winner_lacks_it(monkeypatch):
    calls = _stub_gather(monkeypatch, {"cited_by_count": 11})
    vd = {"source": "ACL", "title": "Paper"}  # no DOI in the winner
    backfill_enrichment(vd, {"doi": "https://doi.org/10.18653/v1/2020.acl-main.1"})
    assert calls["n"] == 1
    assert vd["cited_by_count"] == 11


def test_backfill_soft_fails_on_gather_exception(monkeypatch):
    def boom(doi):
        raise RuntimeError("network down")

    monkeypatch.setattr(_mod, "_gather_backfill_fields", boom)
    vd = {"doi": "10.1/x", "source": "DBLP", "title": "Paper"}
    # Must NOT raise — soft-fail — and must leave the payload intact.
    out = backfill_enrichment(vd)
    assert out is vd
    assert "cited_by_count" not in vd


def test_backfill_clean_doi_rejects_non_doi():
    # Guard: a bogus / non-DOI-shaped string never resolves to a lookup target.
    assert _mod._clean_doi("not-a-doi") is None
    assert _mod._clean_doi("12345") is None
    assert _mod._clean_doi("") is None
    assert _mod._clean_doi(None) is None
    # Real DOIs normalise to the bare lowercased form regardless of resolver prefix.
    assert _mod._clean_doi("https://doi.org/10.1109/ABC.2021") == "10.1109/abc.2021"
    assert _mod._clean_doi("doi:10.5555/3295222.3295349") == "10.5555/3295222.3295349"


def test_backfill_per_doi_cache_dedupes(monkeypatch):
    # _gather_backfill_fields caches per DOI; calling backfill twice for the
    # same DOI hits the underlying fetchers once. We stub at the fetcher layer
    # so the real cache logic in _gather_backfill_fields is exercised.
    fetch_calls = {"n": 0}

    def fake_openalex(doi):
        fetch_calls["n"] += 1
        return {"cited_by_count": 50}

    monkeypatch.setattr(_mod, "_fetch_openalex_by_doi", fake_openalex)
    monkeypatch.setattr(_mod, "_fetch_crossref_by_doi", lambda doi: {})
    monkeypatch.setattr(_mod, "_fetch_s2_by_doi", lambda doi: {})

    vd1 = {"doi": "10.1/same", "source": "DBLP", "title": "A"}
    vd2 = {"doi": "10.1/same", "source": "DBLP", "title": "B"}
    backfill_enrichment(vd1)
    backfill_enrichment(vd2)
    assert vd1["cited_by_count"] == 50
    assert vd2["cited_by_count"] == 50
    assert fetch_calls["n"] == 1  # second call served from the per-DOI cache
