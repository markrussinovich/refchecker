from refchecker.core.refchecker import ArxivReferenceChecker


def _checker():
    return ArxivReferenceChecker.__new__(ArxivReferenceChecker)


def test_parse_single_author_entry_repairs_split_surname_tokens():
    checker = _checker()

    assert checker._parse_single_author_entry("Chaoqi Y ang") == "Chaoqi Yang"
    assert checker._parse_single_author_entry("Joel Y e") == "Joel Ye"


def test_parse_single_author_entry_keeps_normal_names_unchanged():
    checker = _checker()

    assert checker._parse_single_author_entry("M Westover") == "M Westover"
    assert checker._parse_single_author_entry("Jennifer Collinger") == "Jennifer Collinger"


def test_clean_llm_author_text_applies_spacing_fix_in_structured_authors():
    checker = _checker()

    authors = checker._clean_llm_author_text(
        "Chaoqi Y ang*Joel Y e*Jennifer Collinger"
    )

    assert authors == ["Chaoqi Yang", "Joel Ye", "Jennifer Collinger"]
