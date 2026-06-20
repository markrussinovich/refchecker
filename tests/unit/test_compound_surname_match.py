#!/usr/bin/env python3
"""Regression tests for the NON-FINAL compound-surname author matcher.

A Brazilian/Iberian (or tussenvoegsel) citation often abbreviates a name by its
INNER compound surname plus initials, e.g. 'de Oliveira SD' for
'Danilo de Oliveira Silva' (D = Danilo, S = Silva). The strict Vancouver matcher
only anchored the cited surname at the HEAD or TAIL of the full name, so these
inner-run cases were wrongly reported as a mismatch.

The targeted fallback in ``_vancouver_fullname_match`` fires only when BOTH:
  (1) every cited surname word appears in the actual name as a CONSECUTIVE token
      run (particles de/da/van/von/… included, case/diacritic-insensitive), AND
  (2) every cited initial is the first letter of a DISTINCT actual token NOT in
      that surname run (bijective cover — each actual token used at most once).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import (  # noqa: E402
    compare_authors,
    enhanced_name_match,
)


# ── POSITIVE: inner compound surname + covered initials must now match ──────

def test_inner_compound_surname_two_initials():
    # 'de Oliveira' is an INNER run of 'Danilo de Oliveira Silva';
    # S -> Silva, D -> Danilo cover both initials with distinct tokens.
    assert enhanced_name_match('de Oliveira SD', 'Danilo de Oliveira Silva') is True
    assert compare_authors(['de Oliveira SD'], ['Danilo de Oliveira Silva'])[0] is True


def test_inner_compound_surname_single_initial():
    # One initial (S -> Silva) is enough; the leftover actual token 'Danilo'
    # is allowed (a single cited given-initial need not exhaust the name).
    assert enhanced_name_match('de Oliveira S', 'Danilo de Oliveira Silva') is True
    assert compare_authors(['de Oliveira S'], ['Danilo de Oliveira Silva'])[0] is True


def test_final_surname_with_inner_initials():
    # Cited surname IS the final family token 'Silva'; D -> Danilo, O -> Oliveira
    # cover the two initials from the remaining (non-surname) tokens.
    assert enhanced_name_match('Silva DO', 'Danilo de Oliveira Silva') is True
    assert compare_authors(['Silva DO'], ['Danilo de Oliveira Silva'])[0] is True


def test_van_der_compound_run_with_given_initials():
    # Tussenvoegsel analogue: 'van der Berg' run + J -> Jan, K -> Klaas.
    assert enhanced_name_match('van der Berg JK', 'Jan Klaas van der Berg') is True
    assert compare_authors(['van der Berg JK'], ['Jan Klaas van der Berg'])[0] is True


# ── PRECISION: must STILL be a mismatch (no false positives) ────────────────

def test_uncovered_initials_reject():
    # Initials X, Y have no covering token in 'Danilo de Oliveira Silva'.
    assert enhanced_name_match('de Oliveira XY', 'Danilo de Oliveira Silva') is False
    assert compare_authors(['de Oliveira XY'], ['Danilo de Oliveira Silva'])[0] is False


def test_absent_surname_reject():
    # 'Smith' does not appear in the actual name at all -> no surname run.
    assert enhanced_name_match('Smith AB', 'Danilo de Oliveira Silva') is False
    assert compare_authors(['Smith AB'], ['Danilo de Oliveira Silva'])[0] is False


def test_wrong_final_surname_reject():
    # Cited claims the family name 'Silva', but the actual final surname is
    # 'Souza' -> the surname run is absent, so this stays a genuine mismatch.
    # (NOTE: the inner-run form 'de Oliveira SD' is an irreducibly identical
    #  abbreviation of both '... Silva' and '... Souza' — same tokens, same
    #  initials — so the family-name-anchored form is used to exercise the
    #  "wrong final surname" precision intent deterministically.)
    assert enhanced_name_match('Silva DO', 'Danilo de Oliveira Souza') is False
    assert compare_authors(['Silva DO'], ['Danilo de Oliveira Souza'])[0] is False


def test_two_different_people_reject():
    assert enhanced_name_match('Maria Santos', 'Joao Pereira Costa') is False
    assert compare_authors(['Maria Santos'], ['Joao Pereira Costa'])[0] is False


# ── precision: a single cited initial must still cover a real token ─────────

def test_initial_with_no_covering_token_reject():
    # 'de Oliveira K' — K has no covering token among {Danilo, Silva}.
    assert enhanced_name_match('de Oliveira K', 'Danilo de Oliveira Silva') is False
    assert compare_authors(['de Oliveira K'], ['Danilo de Oliveira Silva'])[0] is False
