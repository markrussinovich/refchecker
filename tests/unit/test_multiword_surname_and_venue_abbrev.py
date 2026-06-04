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


def test_two_word_surname_secondary_initial_tolerated():
    # 'Inarejos Clemente EJ' ↔ 'E. I. Inarejos Clemente' — two-word surname,
    # first initial agrees, second differs (J vs I). A two-word surname is
    # distinctive enough to accept (user-confirmed: this was a false positive).
    assert enhanced_name_match('Inarejos Clemente EJ', 'E. I. Inarejos Clemente') is True


def test_single_word_surname_secondary_conflict_still_mismatches():
    # Single-token surname keeps the strict rule.
    assert enhanced_name_match('Smith JA', 'J. B. Smith') is False


def test_different_person_same_initial_not_overmatched():
    assert enhanced_name_match('Smith J', 'Jane Doe') is False


# ── author: the v0.7.85 batch of reported false-positives ─────────────────

def test_initial_glued_to_particle_is_split():
    # 'Rvan der Straaten' is really 'R. van der Straaten' (extraction glued the
    # initial onto the leading particle).
    assert enhanced_name_match('Rvan der Straaten', 'R. van der Straaten') is True


def test_dutch_particle_reordering():
    # 'van de Kremers-Hei K' ↔ 'K. Kremers-van de Hei' — tussenvoegsel reordered.
    assert enhanced_name_match('van de Kremers-Hei K', 'K. Kremers-van de Hei') is True


def test_vancouver_more_initials_than_record():
    # Cited carries more initials than the DB's single given name.
    assert enhanced_name_match('Newcomb NRA', 'Nicolas Newcomb') is True


def test_particle_surname_secondary_initial_differs():
    # Same first initial + distinctive particle surname; a middle initial
    # differs ('RA' vs given 'R D'). Tolerated for particle surnames.
    assert enhanced_name_match('da Silva RA', 'R. D. da Silva') is True
    assert enhanced_name_match('de Oliveira MR', 'M. D. de Oliveira') is True


def test_middle_name_usage():
    # 'LS Lohmander' ↔ 'Stefan Lohmander' (publishes under his middle name).
    assert enhanced_name_match('LS Lohmander', 'Stefan Lohmander') is True


def test_surname_first_database_order():
    # Databases return medical author lists surname-FIRST ('Dürr Hans Roland').
    assert enhanced_name_match('Durr HR', 'Dürr Hans Roland') is True
    assert enhanced_name_match('Schaefer IM', 'Schaefer Inga-Marie') is True
    assert enhanced_name_match('Stacchiotti S', 'Stacchiotti Silvia') is True


def test_diacritic_stripped_not_transliterated():
    # 'ü' must strip to 'u' (cited 'Durr'/'Koter'), not transliterate to 'ue'.
    assert enhanced_name_match('Durr HR', 'Dürr Hans Roland') is True
    assert enhanced_name_match('Koter S', 'S. Koëter') is True
    assert enhanced_name_match('Klassbo M', 'M. Klässbo') is True


def test_middle_name_rule_restricted_to_second_initial():
    # 'LS Lohmander' ↔ 'Stefan Lohmander' (Stefan == 2nd initial S) matches, but
    # 'Newcomb NRA' vs 'Anders Newcomb' (Anders == 3rd initial A) must NOT.
    assert enhanced_name_match('LS Lohmander', 'Stefan Lohmander') is True
    assert enhanced_name_match('Newcomb NRA', 'Anders Newcomb') is False


def test_different_surname_never_matches_via_new_rules():
    assert enhanced_name_match('JM Smith', 'David Jones') is False
    assert enhanced_name_match('van der Berg K', 'J. van der Berg') is False
    assert enhanced_name_match('Durr HR', 'Schmidt Hans Roland') is False


# ── author lists: garbage filtering + consortium ──────────────────────────

def test_garbage_author_entries_filtered_from_count():
    # DB leaked email/delimiter fragments inflating the count; the 4 real
    # authors all match, so it should NOT be a count mismatch.
    cited = ['AK Nilsdotter', 'LS Lohmander', 'M Klassbo', 'EM Roos']
    correct = ['A. Nilsdotter', 'Stefan Lohmander', 'M. Klässbo', 'E. M. Roos',
               'Stefan Se ; L', 'Klässbo-Maria Klassbo@liv Maria', 'M. Se ; Ewa']
    assert compare_authors(cited, correct)[0] is True


def test_consortium_author_covers_members():
    cited = ['Flevas DA', 'Brenneis M', 'TKAF Consortium']
    correct = ['D. Flevas', 'M. Brenneis'] + [f'Member {i}' for i in range(38)]
    assert compare_authors(cited, correct)[0] is True


def test_consortium_with_wrong_named_author_still_fails():
    cited = ['Wrongperson X', 'TKAF Consortium']
    correct = ['D. Flevas', 'M. Brenneis', 'Member 1']
    assert compare_authors(cited, correct)[0] is False


# ── venue: colon subtitle + Jt→Joint abbreviation ─────────────────────────

def test_venue_colon_subtitle_core_match():
    long = ('European spine journal: official publication of the European spine '
            'Society, the European spinal deformity Society')
    assert are_venues_substantially_different(long, 'European spine journal') is False


def test_venue_abbreviated_core_with_subtitle():
    long = 'Eur Spine Journal: Official Publication Eur Spine Soc Eur Spinal Deformity Soc'
    assert are_venues_substantially_different(long, 'European spine journal') is False


def test_venue_first_last_letter_abbrev():
    # 'Jt'->'Joint', and '&' connector dropped.
    assert are_venues_substantially_different(
        'Arch Bone Jt Surg', 'Archives of Bone & Joint Surgery') is False


def test_venue_core_match_does_not_overmatch():
    assert va.venues_core_match('European Spine Journal', 'European Heart Journal') is False
    assert va.venues_core_match('Arch Bone Jt Surg', 'Archives of Internal Medicine') is False


def test_venue_part_designator_preserved():
    # 'Am J Med Genet A' ↔ 'American Journal of Medical Genetics. Part A' — the
    # structural 'Part' is dropped but the 'A' designator is preserved.
    assert are_venues_substantially_different(
        'Am J Med Genet A', 'American Journal of Medical Genetics. Part A') is False
    # Part A vs Part B must STILL differ (the letter distinguishes them).
    assert are_venues_substantially_different(
        'Am J Med Genet A', 'American Journal of Medical Genetics. Part B') is True
    assert are_venues_substantially_different(
        'Am J Med Genet B', 'American Journal of Medical Genetics. Part A') is True


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
