import requests
from unittest.mock import patch

from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker


class NoMatchChecker:
    def verify_reference(self, reference):
        return None, [], None


class TimeoutChecker:
    def verify_reference(self, reference):
        raise requests.exceptions.Timeout('simulated timeout')


class LocalMatchChecker:
    database_label = "Semantic Scholar"
    database_key = "local_s2"

    def verify_reference(self, reference):
        return (
            {
                "title": reference.get("title", ""),
                "paperId": "s2-match-id",
            },
            [],
            "https://www.semanticscholar.org/paper/s2-match-id",
        )


class LocalArxivMismatchChecker:
    database_label = "Semantic Scholar"
    database_key = "local_s2"

    def verify_reference(self, reference):
        return (
            {
                "title": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                "authors": [
                    {"name": "Fengjun Pan"},
                    {"name": "Xiaobao Wu"},
                    {"name": "Tho Quan"},
                    {"name": "Anh Tuan Luu"},
                ],
                "year": 2025,
                "externalIds": {"ArXiv": "2506.08477"},
            },
            [
                {
                    "error_type": "title",
                    "error_details": "Title mismatch",
                    "ref_title_correct": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                },
                {
                    "error_type": "author",
                    "error_details": "Author count mismatch: 3 cited vs 4 correct",
                    "ref_authors_correct": "Fengjun Pan, Xiaobao Wu, Tho Quan, Anh Tuan Luu",
                },
            ],
            "https://api.semanticscholar.org/CorpusID:test",
        )


class ArxivVersionWarningChecker:
    def is_arxiv_reference(self, reference):
        return False

    def verify_reference(self, reference):
        assert reference["url"] == "https://arxiv.org/abs/2506.08477"
        return (
            {
                "title": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                "authors": [
                    {"name": "Fengjun Pan"},
                    {"name": "Xiaobao Wu"},
                    {"name": "Tho Quan"},
                    {"name": "Anh Tuan Luu"},
                ],
                "year": 2025,
                "externalIds": {"ArXiv": "2506.08477"},
            },
            [
                {
                    "warning_type": "title (v1 vs v2 update)",
                    "warning_details": "Title mismatch (v1 vs v2 update)",
                    "ref_title_correct": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                },
                {
                    "warning_type": "author (v1 vs v2 update)",
                    "warning_details": "Author count mismatch: 3 cited vs 4 correct (v1 vs v2 update)",
                    "ref_authors_correct": "Fengjun Pan, Xiaobao Wu, Tho Quan, Anh Tuan Luu",
                },
            ],
            "https://arxiv.org/abs/2506.08477v1",
        )


class ArxivTitleSearchChecker:
    def is_arxiv_reference(self, reference):
        return False

    def extract_arxiv_id(self, reference):
        return None, None

    def find_arxiv_id_by_title(self, title, authors=None, year=None):
        assert title == 'Retrospective for the dynamics sensorium competition for predicting large-scale mouse primary visual cortex activity from videos'
        return '2407.09100'

    def verify_reference(self, reference):
        assert reference['url'] == 'https://arxiv.org/abs/2407.09100'
        return (
            {
                'title': 'Retrospective for the Dynamic Sensorium Competition for predicting large-scale mouse primary visual cortex activity from videos',
                'authors': [
                    {'name': 'Polina Turishcheva'},
                    {'name': 'Paul G. Fahey'},
                    {'name': 'Michaela Vystrčilová'},
                ],
                'year': 2024,
                'externalIds': {'ArXiv': '2407.09100'},
            },
            [],
            'https://arxiv.org/abs/2407.09100',
        )


class WrongOpenReviewChecker:
    def __init__(self):
        self.called = False

    def verify_reference_by_search(self, reference):
        self.called = True
        return (
            {
                'title': 'The sensorium competition on predicting large-scale mouse primary visual cortex activity',
                'authors': ['Konstantin F. Willeke', 'Paul G. Fahey'],
                'year': 2022,
                '_matched_database': 'OpenReview',
            },
            [{'warning_type': 'author', 'warning_details': 'wrong paper'}],
            'https://openreview.net/forum?id=2aphixM7rbf',
        )


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


def test_verify_reference_records_matched_database_from_local_checker():
    checker = _build_checker()
    checker.local_db = LocalMatchChecker()
    checker.semantic_scholar = None
    checker.crossref = None

    verified_data, errors, url = checker.verify_reference({"title": "Test title", "authors": []})

    assert errors == []
    assert url == "https://www.semanticscholar.org/paper/s2-match-id"
    assert verified_data["_matched_database"] == "Semantic Scholar"
    assert verified_data["_matched_checker"] == "local_s2"


def test_shared_postprocess_converts_arxiv_version_mismatch_to_warnings():
    checker = _build_checker()
    checker.local_db = LocalArxivMismatchChecker()
    checker.semantic_scholar = None
    checker.crossref = None
    checker.arxiv_citation = ArxivVersionWarningChecker()

    reference = {
        "title": "Detecting harmful memes with decoupled understanding and guided cot reasoning",
        "authors": ["Fengjun Pan", "Anh Tuan Luu", "Xiaobao Wu"],
        "year": 2025,
        "venue": "arXiv:2506.08477",
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert url == "https://arxiv.org/abs/2506.08477v1"
    assert verified_data["_matched_database"] == "ArXiv"
    assert all("warning_type" in error for error in errors)
    assert not any("error_type" in error for error in errors)
    assert any(error["warning_type"] == "title (v1 vs v2 update)" for error in errors)
    assert any(error["warning_type"] == "author (v1 vs v2 update)" for error in errors)


def test_arxiv_title_search_precedes_loose_openreview_match():
    checker = _build_checker()
    checker.arxiv_citation = ArxivTitleSearchChecker()
    checker.local_db = NoMatchChecker()
    checker.semantic_scholar = NoMatchChecker()
    checker.crossref = None
    checker.openreview = WrongOpenReviewChecker()

    reference = {
        'title': 'Retrospective for the dynamics sensorium competition for predicting large-scale mouse primary visual cortex activity from videos',
        'authors': ['Polina Turishcheva', 'Paul Fahey', 'Michaela Vystrčilová'],
        'year': 2024,
        'venue': 'Advances in Neural Information Processing Systems',
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert errors == []
    assert url == 'https://arxiv.org/abs/2407.09100'
    assert verified_data['_matched_database'] == 'ArXiv'
    assert verified_data['_matched_checker'] == 'arxiv_citation'
    assert checker.openreview.called is False
