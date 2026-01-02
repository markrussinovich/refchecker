import pytest

from refchecker.utils.text_utils import clean_author_name, enhanced_name_match, format_author_for_display


def test_honorific_not_stripped_inside_name():
    # Ensure we don't strip 'Mr' from names like 'Mrinmaya'
    original = "Mrinmaya Sachan"
    cleaned = clean_author_name(original)
    assert cleaned == original


def test_honorific_stripped_at_start():
    assert clean_author_name("Mr. John Smith") == "John Smith"
    assert clean_author_name("Ms Jane Doe") == "Jane Doe"
    assert clean_author_name("Prof. Ada Lovelace") == "Ada Lovelace"
    assert clean_author_name("Professor Alan Turing") == "Alan Turing"
    assert clean_author_name("Dr Albert Einstein") == "Albert Einstein"


def test_enhanced_name_match_intended_behavior():
    # Sanity: matching works around initials and cases
    assert enhanced_name_match("M. Sachan", "Mrinmaya Sachan")
    # Display formatting shouldn't alter name content
    assert format_author_for_display("Sachan, Mrinmaya") == "Mrinmaya Sachan"
