from refchecker.utils.text_utils import are_venues_substantially_different, normalize_venue_for_display


def test_strip_leading_editors_from_venue():
    cited = "Marie-Francine Moens, Xuanjing Huang, Lucia Specia, and Scott Wen-tau Yih, editors, Proceedings of the Conference on Empirical Methods in Natural Language Processing"
    normalized = normalize_venue_for_display(cited)
    assert normalized.startswith("Conference on Empirical Methods in Natural Language Processing")


def test_strip_eds_abbrev_from_venue():
    cited = "A. Smith; B. Jones, eds., Proceedings of the International Conference on Widgets"
    normalized = normalize_venue_for_display(cited)
    assert normalized.startswith("International Conference on Widgets")


def test_strip_parenthesized_eds_acl_proceedings_metadata():
    cited = r"Bouamor, H., Pino, J., and Bali, K. (eds.), Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing, pp.\ 12076--12100, Singapore, December 2023. Association for Computational Linguistics"
    actual = "Conference on Empirical Methods in Natural Language Processing"

    assert normalize_venue_for_display(cited) == actual
    assert not are_venues_substantially_different(cited, actual)


def test_generic_proceedings_leftover_becomes_empty():
    cited = "Proceedings of the"
    normalized = normalize_venue_for_display(cited)
    assert normalized == ""
