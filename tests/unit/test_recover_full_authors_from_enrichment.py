#!/usr/bin/env python3
"""
Unit tests for recover_full_authors_from_enrichment (Issue #56).

When a reference's authors are stored as a truncated "<Author> et al." (the
parser emits a literal "et al" sentinel in the list), the full author list
should be recovered from the verified work's enrichment.authors — REAL DATA
ONLY, never invented. When the cited list is already complete, or there is no
richer verified data, the cited list must be left unchanged (return None).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

try:
    from refchecker.utils.text_utils import recover_full_authors_from_enrichment
except Exception:
    # The refchecker package __init__ eagerly imports heavy modules (e.g. tqdm)
    # that may be absent in a stdlib-only environment. text_utils itself is
    # stdlib-pure, so load it directly from its file as a fallback.
    import importlib.util

    _tu_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'src',
        'refchecker', 'utils', 'text_utils.py',
    )
    _spec = importlib.util.spec_from_file_location('_text_utils_standalone', _tu_path)
    _tu = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_tu)
    recover_full_authors_from_enrichment = _tu.recover_full_authors_from_enrichment


def test_recovers_full_list_when_truncated_with_et_al():
    cited = ["Smith", "et al"]
    enriched = [
        {"name": "John Smith"},
        {"name": "Jane Doe"},
        {"name": "Alan Turing"},
    ]
    out = recover_full_authors_from_enrichment(cited, enriched)
    assert out == ["John Smith", "Jane Doe", "Alan Turing"]


def test_recovers_with_trailing_period_sentinel():
    cited = ["Vaswani", "et al."]
    enriched = [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}]
    out = recover_full_authors_from_enrichment(cited, enriched)
    assert out == ["Ashish Vaswani", "Noam Shazeer"]


def test_accepts_plain_string_enrichment_names():
    cited = ["Smith", "et al"]
    enriched = ["John Smith", "Jane Doe"]
    out = recover_full_authors_from_enrichment(cited, enriched)
    assert out == ["John Smith", "Jane Doe"]


def test_no_override_when_cited_list_already_complete():
    # No "et al." sentinel — leave untouched.
    cited = ["John Smith", "Jane Doe"]
    enriched = [{"name": "John Smith"}, {"name": "Jane Doe"}, {"name": "X Y"}]
    assert recover_full_authors_from_enrichment(cited, enriched) is None


def test_no_override_when_enrichment_not_richer():
    # Single real cited author + "et al"; DB has exactly one name → not richer.
    cited = ["Smith", "et al"]
    enriched = [{"name": "John Smith"}]
    assert recover_full_authors_from_enrichment(cited, enriched) is None


def test_no_override_without_enrichment_authors():
    cited = ["Smith", "et al"]
    assert recover_full_authors_from_enrichment(cited, None) is None
    assert recover_full_authors_from_enrichment(cited, []) is None


def test_never_invents_when_enrichment_is_only_sentinels():
    cited = ["Smith", "et al"]
    enriched = [{"name": "et al"}, {"name": "others"}]
    assert recover_full_authors_from_enrichment(cited, enriched) is None


def test_handles_others_sentinel_variant():
    cited = ["Smith", "and others"]
    enriched = [{"name": "John Smith"}, {"name": "Jane Doe"}]
    out = recover_full_authors_from_enrichment(cited, enriched)
    assert out == ["John Smith", "Jane Doe"]


def test_non_list_cited_returns_none():
    assert recover_full_authors_from_enrichment("Smith et al", [{"name": "A B"}]) is None
    assert recover_full_authors_from_enrichment([], [{"name": "A B"}]) is None
