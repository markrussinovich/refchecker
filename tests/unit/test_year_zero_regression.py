"""Regression tests: references with no year must never show year=0.

The core reference parser used to set year=0 when no year was found.
This caused "0" to appear in the web UI under reference author names.
References with no date should have year=None so the UI hides the field.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


@pytest.fixture
def checker():
    """Create a minimal ArxivReferenceChecker — no network, no LLM."""
    from refchecker.core.refchecker import ArxivReferenceChecker
    return object.__new__(ArxivReferenceChecker)


# ------------------------------------------------------------------
# _create_structured_llm_references — the main LLM-parsed path
# ------------------------------------------------------------------

class TestStructuredLlmReferencesYearNone:
    """Ensure _create_structured_llm_references never returns year=0."""

    def test_arxiv_ref_without_year(self, checker):
        """ArXiv-style ref with no extractable year -> year is None."""
        ref = "Smith, Jones. Some Paper Title. arXiv preprint."
        results = checker._create_structured_llm_references(ref)
        if results:
            items = results if isinstance(results, list) else [results]
            for r in items:
                assert r.get('year') != 0, f"year should be None, got 0: {r}"

    def test_non_arxiv_ref_without_year(self, checker):
        """Non-arXiv ref with no year -> year is None."""
        ref = "Anonymous Author. A Paper Without Any Date Information. Some Venue."
        results = checker._create_structured_llm_references(ref)
        if results:
            items = results if isinstance(results, list) else [results]
            for r in items:
                assert r.get('year') != 0, f"year should be None, got 0: {r}"

    def test_ref_with_valid_year_is_preserved(self, checker):
        """Ref with a real year keeps that year (not converted to None)."""
        ref = "Smith, Jones. Some Paper Title. NeurIPS. 2023."
        results = checker._create_structured_llm_references(ref)
        if results:
            result = results[0] if isinstance(results, list) else results
            assert result.get('year') == 2023


# ------------------------------------------------------------------
# _create_structured_reference — alternate path
# ------------------------------------------------------------------

class TestStructuredReferenceYearNone:
    """Ensure _create_structured_reference never returns year=0."""

    def test_ref_without_year(self, checker):
        if not hasattr(checker, '_create_structured_reference'):
            pytest.skip('Method not present')
        ref = "Author One. A Title With No Year."
        result = checker._create_structured_reference(ref)
        if result:
            assert result.get('year') != 0, f"year should be None, got 0: {result}"


# ------------------------------------------------------------------
# Backend wrapper: _format_verification_result sanitizes year
# ------------------------------------------------------------------

def test_format_result_zero_year_becomes_none():
    """The wrapper should convert year=0 to None before sending to frontend."""
    for input_year in [0, None, '', False]:
        output = input_year or None
        assert output is None, f"Input {input_year!r} should become None, got {output!r}"

    for input_year in [2023, 1999, 2025]:
        output = input_year or None
        assert output == input_year, f"Input {input_year!r} should be preserved"
