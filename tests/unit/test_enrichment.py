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
