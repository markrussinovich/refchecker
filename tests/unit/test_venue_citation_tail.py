"""LLM extraction sometimes returns the tail of the raw citation as the venue.

Every one of these strings came out of a real production check (id 952,
"Fool's Gold"), where 15 of 75 references carried a venue like:

    Tian, "BioProBench: A corpus and benchmark ...," in International
    Conference on Machine Learning (ICML) , 2026

The reference then rendered its title twice in the UI, and every venue
comparison ran against a string that could never match the real venue.
"""

import pytest

from refchecker.core.refchecker import ArxivReferenceChecker


@pytest.fixture
def checker():
    # The fixup is pure string work; a full __init__ would need network config.
    return ArxivReferenceChecker.__new__(ArxivReferenceChecker)


def _fix(checker, venue, title='Some Title', authors=None):
    ref = {'title': title, 'venue': venue, 'authors': authors or []}
    checker._strip_citation_tail_from_venue(ref)
    return ref['venue']


@pytest.mark.parametrize('venue,expected', [
    (
        'Tian, \u201cBioProBench: A corpus and benchmark for biological protocol '
        'reasoning in autonomous science,\u201d in International Conference on '
        'Machine Learning (ICML) , 2026',
        'International Conference on Machine Learning (ICML)',
    ),
    (
        'Bau, \u201cMass-editing memory in a transformer,\u201d in International '
        'Conference on Learning Representations (ICLR) , 2023',
        'International Conference on Learning Representations (ICLR)',
    ),
    (
        'Rivest, \u201cHoneywords: Making password-cracking de-tectable,\u201d in '
        'ACM SIGSAC Conference on Computer and Communications Security (CCS) , 2013',
        'ACM SIGSAC Conference on Computer and Communications Security (CCS)',
    ),
    (
        'Finn, \u201cSelf-destructing models: Increasing the costs of harmful dual '
        'uses of foundation models,\u201d in AAAI/ACM Conference on AI, Ethics, '
        'and Society (AIES) , 2023',
        'AAAI/ACM Conference on AI, Ethics, and Society (AIES)',
    ),
])
def test_citation_tail_reduces_to_the_venue(checker, venue, expected):
    assert _fix(checker, venue) == expected


@pytest.mark.parametrize('venue,expected', [
    # Trailing notes after the year are citation metadata, not venue.
    (
        'The WMDP benchmark: Measuring and reducing malicious use with '
        'unlearning,\u201d in International Conference on Machine Learning '
        '(ICML) , 2024, WMDP benchmark and RMU unlearning method',
        'International Conference on Machine Learning (ICML)',
    ),
    (
        'Wang, \u201cSelf-destructive language models,\u201d in International '
        'Conference on Learning Representations (ICLR) , 2026, SEAM',
        'International Conference on Learning Representations (ICLR)',
    ),
    (
        'SOPHON: Non-fine-tunable learning to restrain task transferability for '
        'pre-trained models,\u201d in IEEE Symposium on Security and Privacy '
        '(S&P) , 2024, arXiv:2404',
        'IEEE Symposium on Security and Privacy (S&P)',
    ),
])
def test_notes_after_the_year_are_dropped(checker, venue, expected):
    assert _fix(checker, venue) == expected


def test_unquoted_venue_is_left_alone(checker):
    """The overwhelmingly common case must not be touched."""
    venue = 'International Conference on Machine Learning (ICML)'
    assert _fix(checker, venue) == venue


@pytest.mark.parametrize('venue', [
    'ICLR 2024',
    'Proceedings of the 2024 Conference on Empirical Methods in NLP',
    'NeurIPS 2023 Workshop on Instruction Tuning',
])
def test_a_year_inside_a_real_venue_survives(checker, venue):
    """Cutting at any year would truncate venues that legitimately carry one;
    only a comma-separated year is citation metadata."""
    assert _fix(checker, venue) == venue


def test_venue_that_is_only_a_quoted_title_is_cleared(checker):
    """A venue with nothing but the title left is noise; blank beats a string
    that fails every comparison and renders the title a second time."""
    assert _fix(checker, '\u201cAttention is all you need\u201d') == ''


def test_straight_quotes_are_handled(checker):
    venue = 'Smith, "Some paper title," in Conference on Neural Information ' \
            'Processing Systems (NeurIPS), 2024'
    assert _fix(checker, venue) == 'Conference on Neural Information Processing Systems (NeurIPS)'


def test_missing_in_keyword_still_drops_the_quoted_title(checker):
    """Not every style uses "in"; the part after the closing quote is still
    the only candidate for a venue."""
    venue = '\u201cSome paper title,\u201d Journal of Machine Learning Research, 2021'
    assert _fix(checker, venue) == 'Journal of Machine Learning Research'


def test_non_string_venue_is_ignored(checker):
    ref = {'title': 'T', 'venue': None, 'authors': []}
    checker._strip_citation_tail_from_venue(ref)
    assert ref['venue'] is None


def test_fixup_entrypoint_applies_the_venue_cleanup(checker):
    """The cleanup must run from _fixup_reference_fields, which is the shared
    post-parse hook every path goes through."""
    ref = {
        'title': 'BioProBench: A corpus and benchmark for biological protocol '
                 'reasoning in autonomous science',
        'authors': ['Y. Liu', 'Y. Tian'],
        'venue': 'Tian, \u201cBioProBench: A corpus and benchmark for biological '
                 'protocol reasoning in autonomous science,\u201d in International '
                 'Conference on Machine Learning (ICML) , 2026',
    }
    checker._fixup_reference_fields(ref)
    assert ref['venue'] == 'International Conference on Machine Learning (ICML)'
    assert ref['title'].startswith('BioProBench')
