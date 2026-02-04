import pytest

from refchecker.utils.text_utils import calculate_title_similarity, normalize_venue_for_display


def test_title_similarity_ignores_trailing_year():
    a = "Phi-4 technical report, 2024"
    b = "Phi-4 Technical Report"
    score = calculate_title_similarity(a, b)
    assert score >= 0.95


def test_normalize_venue_generic_phrase_collapses_to_empty():
    cited = "Proceedings of the"
    assert normalize_venue_for_display(cited) == ""


def test_normalize_venue_preserves_communications_of_the_acm():
    """Venue 'Communications of the ACM' should NOT have ACM stripped (it's part of the name)."""
    cited = "Communications of the ACM"
    assert normalize_venue_for_display(cited) == "Communications of the ACM"


def test_normalize_venue_preserves_journal_of_the_acm():
    """Venue 'Journal of the ACM' should NOT have ACM stripped."""
    cited = "Journal of the ACM"
    assert normalize_venue_for_display(cited) == "Journal of the ACM"


def test_normalize_venue_strips_acm_suffix_when_not_part_of_name():
    """Trailing 'ACM' should be stripped when it's just an org suffix (not preceded by 'of the')."""
    cited = "Conference on Machine Learning ACM"
    assert normalize_venue_for_display(cited) == "Conference on Machine Learning"
