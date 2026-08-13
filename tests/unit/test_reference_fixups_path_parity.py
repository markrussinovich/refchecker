"""Post-parse fixups must run on every path, not just the CLI.

``_fixup_reference_fields`` lived on ``ArxivReferenceChecker`` and was invoked
from ``verify_reference_standard``. The WebUI never calls either: its wrapper
calls ``self.checker.verify_reference(...)`` on the hybrid checker directly. So
the venue-as-title, author-list-as-title and citation-tail-as-venue repairs were
silently skipped in the WebUI, which is why the user still saw the citation
title duplicated into the venue after the fix shipped.

The fixups now live in a shared module and are applied at the hybrid checker's
entry point — the one place all three paths funnel through.
"""

import pytest

from refchecker.utils.reference_fixups import (
    fixup_reference_fields,
    strip_citation_tail_from_venue,
)

# Real production string from the user's paper (reference 74).
CONTAMINATED_VENUE = (
    'Tian, "BioProBench: a benchmark for biological protocols," '
    'in International Conference on Machine Learning (ICML) , 2026'
)
CLEAN_VENUE = 'International Conference on Machine Learning (ICML)'


def _ref(**over):
    base = {'title': 'BioProBench', 'authors': ['Y. Tian'], 'year': 2026,
            'venue': CONTAMINATED_VENUE}
    base.update(over)
    return base


class TestSharedImplementation:
    def test_citation_tail_removed(self):
        ref = _ref()
        fixup_reference_fields(ref)
        assert ref['venue'] == CLEAN_VENUE

    def test_is_idempotent(self):
        """Safe to apply at more than one point in a pipeline."""
        ref = _ref()
        fixup_reference_fields(ref)
        once = ref['venue']
        fixup_reference_fields(ref)
        assert ref['venue'] == once

    @pytest.mark.parametrize('venue', [
        'ICLR 2024',
        'Proceedings of the 2024 Conference on EMNLP',
        'Nature',
        '',
    ])
    def test_legitimate_venues_survive(self, venue):
        ref = _ref(venue=venue)
        fixup_reference_fields(ref)
        assert ref['venue'] == venue

    def test_unsalvageable_venue_is_blanked(self):
        """A blank venue beats one that fails every comparison."""
        ref = _ref(venue='"A title," in ab, 2024')
        strip_citation_tail_from_venue(ref)
        assert ref['venue'] == ''


class TestPathParity:
    """The CLI and the WebUI must produce the same corrected reference."""

    def test_cli_entry_point_applies_fixups(self):
        from refchecker.core.refchecker import ArxivReferenceChecker

        checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
        ref = _ref()
        checker._fixup_reference_fields(ref)
        assert ref['venue'] == CLEAN_VENUE

    def test_hybrid_checker_applies_fixups(self):
        """The WebUI reaches this method directly, bypassing the CLI wrapper."""
        from refchecker.checkers.enhanced_hybrid_checker import (
            EnhancedHybridReferenceChecker,
        )

        checker = EnhancedHybridReferenceChecker.__new__(EnhancedHybridReferenceChecker)
        seen = {}

        def _core(reference):
            # Capture the venue as the verification logic actually sees it.
            seen['venue'] = reference.get('venue')
            return None, [], None

        checker._verify_reference_core = _core
        checker._postprocess_verification = lambda vd, e, u, ref: (vd, e, u)

        ref = _ref()
        try:
            checker.verify_reference(ref)
        except Exception:
            # Later stages need a fully constructed instance; the fixup has
            # already run by then, which is all this test asserts.
            pass

        assert seen.get('venue') == CLEAN_VENUE, (
            'The hybrid checker must repair fields before verifying, otherwise '
            'the WebUI skips the fixups entirely'
        )
        assert ref['venue'] == CLEAN_VENUE

    def test_both_paths_agree(self):
        from refchecker.core.refchecker import ArxivReferenceChecker

        cli_ref = _ref()
        ArxivReferenceChecker.__new__(ArxivReferenceChecker)._fixup_reference_fields(cli_ref)

        shared_ref = _ref()
        fixup_reference_fields(shared_ref)

        assert cli_ref == shared_ref


class TestNoDuplicateImplementation:
    """One implementation, so a fix can't reach some paths and miss others."""

    def test_core_delegates_rather_than_reimplementing(self):
        import inspect

        from refchecker.core.refchecker import ArxivReferenceChecker

        source = inspect.getsource(ArxivReferenceChecker._fixup_reference_fields)
        assert 'fixup_reference_fields(reference)' in source
        # The venue-as-title pattern list must exist in exactly one place.
        assert 'Proceedings of the' not in source
