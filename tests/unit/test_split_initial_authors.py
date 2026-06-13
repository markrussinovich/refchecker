"""Regression tests for split-initial author repair in LLM bibliography output.

Several Google Gemini extractions emit '*'-delimited author lists where
"Jang, E., Gu, S., and Poole, B." becomes "E*Jang*S*Gu*B*Poole".  The
naive splitter then produces six "authors": E, Jang, S, Gu, B, Poole,
which fail name matching against canonical metadata.

ArxivReferenceChecker._merge_split_initial_authors must recombine
consecutive (initial, surname) pairs back into "Initial Surname".
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import pytest

from refchecker.core.refchecker import ArxivReferenceChecker


@pytest.fixture
def checker():
    return ArxivReferenceChecker()


def test_simple_split_initials_merged(checker):
    tokens = ["E", "Jang", "S", "Gu", "B", "Poole"]
    result = checker._merge_split_initial_authors(tokens)
    assert result == ["E. Jang", "S. Gu", "B. Poole"]


def test_compound_and_two_letter_initial_merged(checker):
    # "H.-Y" / "A. M" style initial tokens emitted by the LLM
    tokens = ["H.-Y", "Zhou", "A. M", "Saxe"]
    result = checker._merge_split_initial_authors(tokens)
    assert result == ["H.-Y. Zhou", "A. M. Saxe"]


def test_hyphenated_surname_preserved(checker):
    tokens = ["H", "Maron", "H", "Ben-Hamu", "N", "Shamir", "Y", "Lipman"]
    result = checker._merge_split_initial_authors(tokens)
    assert result == ["H. Maron", "H. Ben-Hamu", "N. Shamir", "Y. Lipman"]


def test_full_first_name_left_intact(checker):
    # Already proper "Initial Surname" entries — no bare initials present
    tokens = ["J. S. Hartford", "Y. Bengio", "K. Ahuja"]
    result = checker._merge_split_initial_authors(tokens)
    assert result == tokens


def test_mixed_full_names_not_merged(checker):
    # Real first-name tokens (with lowercase) must not be merged with surnames
    tokens = ["John", "Smith", "Jane", "Doe"]
    result = checker._merge_split_initial_authors(tokens)
    assert result == tokens


def test_surname_comma_initial_left_untouched(checker):
    # "Surname, Initial" form is already valid — refuse to merge anything
    tokens = ["Smith, J.", "Doe, A. B."]
    result = checker._merge_split_initial_authors(tokens)
    assert result == tokens


def test_clean_llm_author_text_repairs_split_initials(checker):
    text = "E*Jang*S*Gu*B*Poole"
    parsed = checker._clean_llm_author_text(text)
    assert parsed == ["E. Jang", "S. Gu", "B. Poole"]


def test_clean_llm_author_text_repairs_compound_initial(checker):
    text = "A. M*Saxe*D*Jarvis*R*Klein*B*Rosman"
    parsed = checker._clean_llm_author_text(text)
    # First token "A. M" is an initial group; surname "Saxe" follows
    assert "A. M. Saxe" in parsed
    assert "D. Jarvis" in parsed
    assert "R. Klein" in parsed
    assert "B. Rosman" in parsed


def test_clean_llm_author_text_preserves_well_formed(checker):
    text = "K. Ahuja*J. S. Hartford*Y. Bengio"
    parsed = checker._clean_llm_author_text(text)
    assert parsed == ["K. Ahuja", "J. S. Hartford", "Y. Bengio"]


def test_clean_llm_author_text_preserves_et_al(checker):
    text = "E*Jang*S*Gu*B*Poole*et al"
    parsed = checker._clean_llm_author_text(text)
    assert "E. Jang" in parsed
    assert parsed[-1] == "et al"


def test_single_initial_alone_not_merged(checker):
    # Only one bare initial — leave it alone (could be a typo, not a pattern)
    tokens = ["E", "John Smith", "Jane Doe"]
    result = checker._merge_split_initial_authors(tokens)
    assert result == tokens
