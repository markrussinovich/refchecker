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
