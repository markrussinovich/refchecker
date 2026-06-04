#!/usr/bin/env python3
"""Regression tests for the author/venue abbreviation matching fixes.

Author: Vancouver 'Surname INITIALS' vs full 'Given... Surname' must match even
for MULTI-WORD / HYPHENATED surnames (Feliu-Soler, Hornicek FJ Jr). Venue:
foreign-language abbreviations (ZBL NEUROCHIR -> Zentralblatt für Neurochirurgie)
must not be flagged as a venue mismatch. Both must stay conservative — a real
difference still mismatches.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import (  # noqa: E402
    enhanced_name_match, compare_authors, are_venues_substantially_different,
)
from refchecker.utils import venue_abbreviations as va  # noqa: E402


# ── author: multi-word / hyphenated surname, Vancouver ↔ full ──────────────

def test_hyphenated_surname_initial_vs_full():
    assert enhanced_name_match('Feliu-Soler A', 'Albert Feliu Soler') is True
    assert compare_authors(['Feliu-Soler A'], ['Albert Feliu Soler'])[0] is True


def test_multiword_initials_with_suffix():
    assert enhanced_name_match('Hornicek FJ Jr', 'Francis John Hornicek Jr') is True


def test_two_word_surname_initials():
    assert enhanced_name_match('Garcia-Lopez M', 'Maria Garcia Lopez') is True


def test_real_initial_difference_still_mismatches():
    # 'EJ' vs given initials 'E I' -> the second initial genuinely differs.
    assert enhanced_name_match('Inarejos Clemente EJ', 'E. I. Inarejos Clemente') is False


def test_different_person_same_initial_not_overmatched():
    assert enhanced_name_match('Smith J', 'Jane Doe') is False


# ── venue: foreign-language abbreviation ───────────────────────────────────

def test_foreign_compound_abbreviation_matches():
    assert va.is_acceptable_abbreviation(
        'ZBL NEUROCHIR', 'Zentralblatt für Neurochirurgie', 'bibtex') is True
    # False == "not substantially different" == venue OK (no mismatch warning)
    assert are_venues_substantially_different(
        'ZBL NEUROCHIR', 'Zentralblatt für Neurochirurgie', 'bibtex') is False


def test_english_word_abbreviation_still_matches():
    assert va.is_acceptable_abbreviation(
        'Eur J Surg Oncol', 'European Journal of Surgical Oncology', 'bibtex') is True


def test_distinct_venues_still_mismatch():
    assert are_venues_substantially_different('Nature', 'Science', 'bibtex') is True


def test_token_abbrev_subsequence_is_gated():
    # prefix
    assert va._token_abbrev_match('neurochir', 'neurochirurgie') is True
    # compound subsequence, same first letter
    assert va._token_abbrev_match('zbl', 'zentralblatt') is True
    # different first letter -> no
    assert va._token_abbrev_match('xbl', 'zentralblatt') is False
    # too short for subsequence path
    assert va._token_abbrev_match('zb', 'zentralblatt') is False
