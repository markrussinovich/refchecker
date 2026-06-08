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
