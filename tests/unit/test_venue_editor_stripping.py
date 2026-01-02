from refchecker.utils.text_utils import normalize_venue_for_display


def test_strip_leading_editors_from_venue():
    cited = "Marie-Francine Moens, Xuanjing Huang, Lucia Specia, and Scott Wen-tau Yih, editors, Proceedings of the Conference on Empirical Methods in Natural Language Processing"
    normalized = normalize_venue_for_display(cited)
    assert normalized.startswith("Conference on Empirical Methods in Natural Language Processing")


def test_strip_eds_abbrev_from_venue():
    cited = "A. Smith; B. Jones, eds., Proceedings of the International Conference on Widgets"
    normalized = normalize_venue_for_display(cited)
    assert normalized.startswith("International Conference on Widgets")


def test_generic_proceedings_leftover_becomes_empty():
    cited = "Proceedings of the"
    normalized = normalize_venue_for_display(cited)
    assert normalized == ""
