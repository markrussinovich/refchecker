"""Regression tests for `_diff_cited_vs_truth` diacritic/unicode folding.

Root cause of the "Unknown mismatch" / spurious-warning bug: the fuzzy-cache
re-check (`_diff_cited_vs_truth`) compared cited-vs-cached fields with a
lower()-only normalizer. A field that matched the cached truth modulo accents
(venue "Émergent" vs "Emergent", author surname "Béngio" vs "Bengio",
"Łukasz" vs "Lukasz") was flagged as a genuine mismatch even though the fields
agree — a false-positive warning on an otherwise verified reference.

These tests pin the fix: accent/unicode/case-only differences raise NO
warning, while genuinely different values still warn.
"""

import pytest

# The wrapper transitively imports the heavy core (pdfplumber etc.); skip
# cleanly in stripped-down environments rather than erroring at collection.
_wrapper = pytest.importorskip("backend.refchecker_wrapper")
_diff_cited_vs_truth = _wrapper._diff_cited_vs_truth


def _all_issue_types(errors, warnings):
    out = []
    for e in errors:
        out.append(e.get("error_type"))
    for w in warnings:
        out.append(w.get("warning_type"))
    return out


def test_venue_accent_only_difference_does_not_warn():
    ref = {
        "title": "A study of methods",
        "authors": ["Smith, John"],
        "year": 2020,
        "venue": "Proceedings of the Conference on Émergent Methods",
    }
    truth = {
        "title": "A study of methods",
        "authors": "Smith, John",
        "year": 2020,
        "venue": "Proceedings of the Conference on Emergent Methods",
    }
    errors, warnings = _diff_cited_vs_truth(ref, truth)
    assert "venue" not in _all_issue_types(errors, warnings), (
        "accent-only venue difference must not raise a venue mismatch"
    )


def test_author_accent_only_difference_does_not_warn():
    # Łukasz vs Lukasz, Béngio vs Bengio — same authors, different encoding.
    ref = {
        "title": "Attention is all you need",
        "authors": ["Béngio, Yoshua", "Łukasz, Kaiser"],
        "year": 2017,
        "venue": "NeurIPS",
    }
    truth = {
        "title": "Attention is all you need",
        "authors": "Bengio, Yoshua, Lukasz, Kaiser",
        "year": 2017,
        "venue": "NeurIPS",
    }
    errors, warnings = _diff_cited_vs_truth(ref, truth)
    types = _all_issue_types(errors, warnings)
    assert "authors" not in types, (
        "accent-only author difference must not raise an author mismatch"
    )


def test_clean_reference_produces_no_issues():
    ref = {
        "title": "Deep residual learning for image recognition",
        "authors": ["He, Kaiming", "Zhang, Xiangyu"],
        "year": 2016,
        "venue": "CVPR",
    }
    truth = {
        "title": "Deep residual learning for image recognition",
        "authors": "He, Kaiming, Zhang, Xiangyu",
        "year": 2016,
        "venue": "CVPR",
    }
    errors, warnings = _diff_cited_vs_truth(ref, truth)
    assert errors == [] and warnings == []


def test_genuine_venue_mismatch_still_warns():
    ref = {
        "title": "Some paper",
        "authors": ["Smith, John"],
        "year": 2020,
        "venue": "NeurIPS",
    }
    truth = {
        "title": "Some paper",
        "authors": "Smith, John",
        "year": 2020,
        "venue": "ICML",
    }
    errors, warnings = _diff_cited_vs_truth(ref, truth)
    assert "venue" in _all_issue_types(errors, warnings), (
        "a real venue difference must still be reported"
    )


def test_genuine_author_mismatch_still_warns():
    ref = {
        "title": "Some paper",
        "authors": ["Smith, John"],
        "year": 2020,
        "venue": "NeurIPS",
    }
    truth = {
        "title": "Some paper",
        "authors": "Jones, Mary",
        "year": 2020,
        "venue": "NeurIPS",
    }
    errors, warnings = _diff_cited_vs_truth(ref, truth)
    assert "authors" in _all_issue_types(errors, warnings), (
        "a real author difference must still be reported"
    )
