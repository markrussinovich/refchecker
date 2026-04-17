import requests
from unittest.mock import patch

from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker


class NoMatchChecker:
    def verify_reference(self, reference):
        return None, [], None


class TimeoutChecker:
    def verify_reference(self, reference):
        raise requests.exceptions.Timeout('simulated timeout')


def _build_checker():
    with patch.object(EnhancedHybridReferenceChecker, '_initialize_checker', return_value=None):
        checker = EnhancedHybridReferenceChecker(
            enable_openalex=False,
            enable_crossref=False,
            enable_arxiv_citation=False,
        )

    checker.local_db = None
    checker.semantic_scholar = NoMatchChecker()
    checker.crossref = TimeoutChecker()
    checker.openalex = None
    checker.dblp = None
    checker.openreview = None
    return checker


@patch('refchecker.checkers.enhanced_hybrid_checker.time.sleep', return_value=None)
def test_unverified_reason_includes_negative_and_failed_checkers(_mock_sleep):
    checker = _build_checker()
    reference = {
        'title': 'Few-shot learning for personalized facial expression recognition',
        'authors': ['Anan Yao', 'Sheng Zhang', 'Ruisha Qian'],
        'venue': 'Proceedings of the 29th ACM International Conference on Multimedia',
        'year': 2021,
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is None
    assert url is None
    assert len(errors) == 1
    assert errors[0]['error_type'] == 'unverified'
    assert errors[0]['error_details'] == (
        'Paper not found by any checker; no match in Semantic Scholar; '
        'checker failures: CrossRef: simulated timeout'
    )
    assert errors[0]['sources_checked'] == 2
    assert errors[0]['sources_negative'] == 1