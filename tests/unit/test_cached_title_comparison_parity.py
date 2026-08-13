"""The cached-verification path must judge titles by the shared rules.

`_diff_cited_vs_truth` runs when the WebUI gets a fuzzy hit in the cross-paper
"Seen References" cache. That cache exists only in the WebUI — the CLI and bulk
runners have no equivalent — so any private comparison logic here means the same
reference is judged by different rules depending purely on whether it happened
to be cached already.

It used to compute a raw token-set Jaccard (no stop-word filtering, no phrase
weighting) and compare it against hand-picked 0.55 / 0.85 cut-offs, entirely
independent of `calculate_title_similarity` and the shared
`similarity_threshold` that every live checker uses. The two disagreed across
the middle of the range, so a reference could come back verified when checked
fresh and warned when replayed from cache.
"""

import pytest

from backend.refchecker_wrapper import (
    _TITLE_MATCH_THRESHOLD,
    _TITLE_MISMATCH_THRESHOLD,
    _diff_cited_vs_truth,
)
from refchecker.config.settings import get_config
from refchecker.utils.text_utils import calculate_title_similarity


def _title_verdict(cited_title, truth_title):
    """'error' | 'warning' | 'clean' for the title comparison alone."""
    errors, warnings = _diff_cited_vs_truth(
        {'title': cited_title, 'year': 2020, 'authors': 'A. Author'},
        {'title': truth_title, 'year': 2020, 'authors': 'A. Author'},
    )
    if any(e.get('error_type') == 'title' for e in errors):
        return 'error'
    if any(w.get('warning_type') == 'title' for w in warnings):
        return 'warning'
    return 'clean'


class TestThresholdsComeFromSharedConfig:
    def test_acceptance_threshold_is_the_shared_one(self):
        expected = float(get_config()['text_processing']['similarity_threshold'])
        assert _TITLE_MATCH_THRESHOLD == expected

    def test_mismatch_tier_sits_below_acceptance(self):
        assert 0 < _TITLE_MISMATCH_THRESHOLD < _TITLE_MATCH_THRESHOLD


class TestAgreesWithTheSharedScorer:
    """A title the checkers would accept must not be flagged from cache."""

    SAME_PAPER = [
        ('A Survey of Large Language Models', 'A Survey on Large Language Models'),
        ('Language Models are Few-Shot Learners', 'Language models are few shot learners'),
        ('ImageNet Classification with Deep Convolutional Neural Networks',
         'ImageNet classification with deep convolutional neural networks'),
        ('Attention Is All You Need', 'Attention Is All You Need'),
    ]

    DIFFERENT_PAPER = [
        ('Attention Is All You Need', 'Deep Residual Learning for Image Recognition'),
        ('Learning to Summarize from Human Feedback',
         'A Survey of Quantum Error Correction Codes'),
    ]

    @pytest.mark.parametrize('cited,truth', SAME_PAPER)
    def test_titles_the_checkers_accept_are_not_flagged(self, cited, truth):
        assert calculate_title_similarity(cited.lower(), truth.lower()) >= _TITLE_MATCH_THRESHOLD
        assert _title_verdict(cited, truth) == 'clean'

    @pytest.mark.parametrize('cited,truth', DIFFERENT_PAPER)
    def test_clearly_different_works_are_errors(self, cited, truth):
        assert _title_verdict(cited, truth) == 'error'

    @pytest.mark.parametrize('cited,truth', SAME_PAPER + DIFFERENT_PAPER)
    def test_clean_boundary_never_diverges_from_the_shared_scorer(self, cited, truth):
        """The single most important property: the 'is this the same paper?'
        answer must be identical on the cached path and the live path."""
        shared_says_same = (
            calculate_title_similarity(cited.lower(), truth.lower()) >= _TITLE_MATCH_THRESHOLD
        )
        cache_says_same = _title_verdict(cited, truth) == 'clean'
        assert cache_says_same == shared_says_same


class TestSeverityIsProportionate:
    def test_spelling_variant_warns_rather_than_erroring(self):
        """A discrepancy to flag, not grounds for 'this is a different paper'."""
        verdict = _title_verdict('Adam: A Method for Stochastic Optimization',
                                 'Adam: A method for stochastic optimisation')
        assert verdict == 'warning'

    def test_subtitle_difference_is_not_flagged(self):
        """A paper cited with its subtitle against a record without one.

        The shared helper deliberately requires a substantial (>=20 char) head
        before accepting a subtitle-only difference, so that a short title like
        "Deep Learning" cannot swallow every paper starting with those words.
        """
        assert _title_verdict(
            'A Torn Discoid Lateral Meniscus Impacts Lower-Limb Alignment '
            'Regardless of Age: surgical treatment may not be appropriate',
            'A Torn Discoid Lateral Meniscus Impacts Lower-Limb Alignment '
            'Regardless of Age') == 'clean'

    def test_short_titled_subtitle_difference_only_warns(self):
        """Below the helper's head-length floor there is not enough evidence to
        call it the same paper — but it must not be escalated to an error."""
        assert _title_verdict(
            'The Menlo Report: Ethical Principles Guiding Information and '
            'Communication Technology Research',
            'The Menlo Report') == 'warning'

    def test_missing_titles_are_not_flagged(self):
        assert _title_verdict('', 'Some Cached Title') == 'clean'
        assert _title_verdict('Some Cited Title', '') == 'clean'


def test_no_private_jaccard_remains():
    """Guard against the private formula creeping back in."""
    import inspect

    source = inspect.getsource(_diff_cited_vs_truth)
    assert '_shared_title_similarity' in source
    assert 'jacc' not in source, 'title comparison must use the shared scorer'
