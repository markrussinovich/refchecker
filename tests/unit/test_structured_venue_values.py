"""A structured venue value must not break the wrong-paper check.

Semantic Scholar returns ``journal`` as an object (``{'name': ..., 'volume':
...}``) and Crossref returns ``container-title`` as a list. The wrong-paper
check fell back from an empty ``venue`` to ``journal``, then called ``.strip()``
on it, raising ``AttributeError: 'dict' object has no attribute 'strip'``. The
caller swallowed that as a checker failure, so a reference the database had
matched was reported unverified instead.

Real case: the Menlo Report (reference 74 of the user's paper). Its Semantic
Scholar record has ``venue: ''`` and ``journal: {'name': '', 'volume': ''}``, so
the CLI reported "Could not verify ... checker failures: Semantic Scholar:
'dict' object has no attribute 'strip'" while the WebUI, hitting the local
database (which returns a plain string), verified it — a path-parity break.
"""

import pytest

from refchecker.checkers.enhanced_hybrid_checker import (
    EnhancedHybridReferenceChecker,
    _venue_text,
)


class TestVenueText:
    def test_none_and_empty(self):
        assert _venue_text(None) == ''
        assert _venue_text('') == ''

    def test_plain_string_is_stripped(self):
        assert _venue_text('  Nature  ') == 'Nature'

    def test_semantic_scholar_journal_object(self):
        assert _venue_text({'name': 'Nature', 'volume': '7'}) == 'Nature'

    def test_empty_journal_object_is_empty(self):
        """The exact shape that triggered the crash."""
        assert _venue_text({'name': '', 'volume': ''}) == ''

    def test_crossref_container_title_list(self):
        assert _venue_text(['Journal of Widgets', 'J. Widgets']) == 'Journal of Widgets'

    def test_openalex_display_name(self):
        assert _venue_text({'display_name': 'ICML'}) == 'ICML'

    def test_unknown_object_falls_back_to_str(self):
        assert _venue_text(2016) == '2016'


class TestVenuesCompatible:
    @pytest.fixture
    def checker(self):
        return EnhancedHybridReferenceChecker.__new__(EnhancedHybridReferenceChecker)

    def test_dict_venue_does_not_raise(self, checker):
        """Would previously raise AttributeError and abort the whole check."""
        assert checker._venues_compatible('', {'name': '', 'volume': ''}) is True

    def test_dict_venue_matches_equivalent_string(self, checker):
        assert checker._venues_compatible('Nature', {'name': 'Nature'}) is True

    def test_list_venue_does_not_raise(self, checker):
        assert checker._venues_compatible(['Nature'], 'Nature') is True

    def test_genuinely_different_venues_still_incompatible(self, checker):
        assert checker._venues_compatible('Nature', {'name': 'ICML'}) is False
