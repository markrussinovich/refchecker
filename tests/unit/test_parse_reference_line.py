"""
Unit tests for _create_structured_llm_references field-swapping fixes.
Tests venue-as-title, author-as-title, and citation-string-as-title detection.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def checker():
    """Create a minimal ArxivReferenceChecker for testing parsing methods."""
    from refchecker.core.refchecker import ArxivReferenceChecker
    obj = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    # Stub only the attributes the parser touches
    obj.db_path = None
    obj.db_paths = {}
    obj.cache_dir = None
    obj.llm_verifier = None
    return obj


class TestVenueAsTitleDetection:
    """Test that venue/journal names parsed as titles are detected and swapped."""

    def test_journal_name_as_title_with_author_fragment(self, checker):
        """When title='Journal of Machine Learning Research' and author contains real title fragment."""
        ref = "tions to fairness, recall, churn, and other goals#Journal of Machine Learning Research##2019#"
        result = checker._create_structured_llm_references(ref)
        # The venue should now be "Journal of Machine Learning Research"
        # and title should be the author fragment (best effort recovery)
        assert "journal of machine learning research" not in result['title'].lower()

    def test_proceedings_as_title_with_author_fragment(self, checker):
        """When title='Proceedings of the IEEE/CVF International Conference on Computer Vision'."""
        ref = "stic 3d scenes#Proceedings of the IEEE/CVF International Conference on Computer Vision##2023#"
        result = checker._create_structured_llm_references(ref)
        assert "proceedings of" not in result['title'].lower()

    def test_real_title_starting_with_journal_not_swapped(self, checker):
        """Titles that happen to start with 'Journal' but are real paper titles should not be swapped."""
        ref = "John Smith#Journal-Guided Learning for Scientific Discovery#Nature#2023#"
        result = checker._create_structured_llm_references(ref)
        # "Journal-Guided" doesn't match "Journal of [A-Z]" pattern
        assert "journal-guided" in result['title'].lower()


class TestAuthorAsTitleDetection:
    """Test that author lists parsed as titles are detected."""

    def test_author_list_as_title(self, checker):
        """When the LLM puts author names in the title field."""
        ref = "#Hunter Lightman Vineet Kosaraju Yuri Burda Harrison Edwards Bowen Baker Teddy Lee Jan Leike John Schulman Ilya Sutskever Karl Cobbe##2023#"
        result = checker._create_structured_llm_references(ref)
        # The author-as-title detector should recognize this as names, not a title
        # Title should be empty (since we can't recover the real one)
        assert result['title'] == ""
        assert result['year'] == 2023

    def test_real_title_with_many_capitalized_words_not_rejected(self, checker):
        """Real titles with capitalized words should not be flagged as author lists."""
        ref = "#Hopfield Networks Is All You Need##2021#"
        result = checker._create_structured_llm_references(ref)
        assert "hopfield" in result['title'].lower()


class TestCitationStringAsTitle:
    """Test that full citation strings parsed as titles are detected."""

    def test_full_citation_as_title(self, checker):
        """When the entire citation is in the title field."""
        ref = "#Davis hp, squire lr. protein synthesis and memory: a review. psychol bull 96: 518-559##1984#"
        result = checker._create_structured_llm_references(ref)
        # Should still parse, possibly as-is
        assert result is not None
        assert result['year'] == 1984
