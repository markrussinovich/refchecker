"""
Regression test: ArXiv refs should use local DB first, then fall back
to ArXiv citation checker if the local DB result has a major author
discrepancy (e.g., corrupt S2 duplicate entry).

Flow:
1. Try local DB (instant) for ArXiv references
2. If local DB result has no major discrepancy → use it
3. If local DB result has major author discrepancy → fall back to ArXiv BibTeX

Test case: DeepSeek-R1 (CorpusID:284488789 has fabricated authors
"Adam Suma, Sam Dauncey" — the ArXiv BibTeX has the real 198 authors).
"""

import unittest
from unittest.mock import MagicMock, patch
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker


class TestLocalDbArxivFallback(unittest.TestCase):

    def _make_checker(self, local_db=None, arxiv_citation=None, semantic_scholar=None):
        checker = EnhancedHybridReferenceChecker.__new__(EnhancedHybridReferenceChecker)
        checker.local_db = local_db
        checker.arxiv_citation = arxiv_citation
        checker.semantic_scholar = semantic_scholar
        checker.crossref = None
        checker.openalex = None
        checker.dblp = None
        checker.openreview = None
        checker.retry_base_delay = 0
        checker.max_retry_delay = 0
        checker.retry_backoff_factor = 1
        checker.max_retries = 0
        checker._api_time_lock = __import__('threading').Lock()
        checker._api_retry_sleep_time = 0.0
        checker._api_times = {}
        checker._api_total_time = {k: 0.0 for k in ['arxiv_citation', 'local_db', 'semantic_scholar', 'crossref', 'openalex', 'dblp', 'openreview']}
        checker._api_sem_wait_time = {k: 0.0 for k in checker._api_total_time}
        checker.api_stats = {k: {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0} for k in checker._api_total_time}
        import threading
        checker._api_semaphores = {k: threading.Semaphore(100) for k in checker._api_total_time}
        checker._last_crossref_result = None
        checker._last_openalex_result = None
        return checker

    def _deepseek_ref(self):
        return {
            'title': 'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning',
            'authors': ['Daya Guo', 'Dejian Yang', 'Haowei Zhang', 'et al.'],
            'year': '2025',
            'url': '',
            'venue': 'arXiv preprint arXiv:2501.12948',
            'raw_text': '',
        }

    def _corrupt_local_db_result(self):
        """Local DB returns corrupt entry with fabricated authors."""
        return (
            {
                'title': 'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning',
                'authors': [{'name': 'Adam Suma'}, {'name': 'Sam Dauncey'}],
                'year': 2025,
                'venue': '',
                'externalIds': {},
                'paperId': 'corrupt_id',
            },
            [{
                'error_type': 'author',
                'error_details': 'Author 1 mismatch\n       cited:  Daya Guo (not found in author list - et al case)\n       actual: Adam Suma, Sam Dauncey',
                'ref_authors_correct': 'Adam Suma, Sam Dauncey',
            }],
            'https://api.semanticscholar.org/CorpusID:284488789',
        )

    def _good_local_db_result(self):
        """Local DB returns correct entry."""
        return (
            {
                'title': 'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning',
                'authors': [{'name': 'Daya Guo'}, {'name': 'Dejian Yang'}],
                'year': 2025,
                'venue': 'Nature',
                'externalIds': {'ArXiv': '2501.12948'},
                'paperId': 'correct_id',
            },
            [],
            'https://api.semanticscholar.org/CorpusID:275789950',
        )

    def _arxiv_citation_result(self):
        """ArXiv BibTeX returns the correct entry."""
        return (
            {
                'title': 'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning',
                'authors': [{'name': 'Daya Guo'}, {'name': 'Dejian Yang'}],
                'year': 2025,
            },
            [],
            'https://arxiv.org/abs/2501.12948',
        )

    def test_local_db_used_when_no_discrepancy(self):
        """If local DB result is clean, use it without calling ArXiv."""
        local_db = MagicMock()
        arxiv_citation = MagicMock()
        arxiv_citation.is_arxiv_reference.return_value = True
        arxiv_citation.extract_arxiv_id.return_value = '2501.12948'

        good = self._good_local_db_result()
        local_db.verify_reference.return_value = good

        checker = self._make_checker(local_db=local_db, arxiv_citation=arxiv_citation)

        ref = self._deepseek_ref()
        paper_data, errors, url = checker.verify_reference(ref)

        # Local DB was called
        local_db.verify_reference.assert_called_once()
        # ArXiv citation was NOT called (no need — local DB was clean)
        arxiv_citation.verify_reference.assert_not_called()
        # Result comes from local DB
        assert paper_data['paperId'] == 'correct_id'

    def test_arxiv_fallback_on_author_discrepancy(self):
        """If local DB has major author discrepancy, fall back to ArXiv."""
        local_db = MagicMock()
        arxiv_citation = MagicMock()
        arxiv_citation.is_arxiv_reference.return_value = True
        arxiv_citation.extract_arxiv_id.return_value = '2501.12948'

        corrupt = self._corrupt_local_db_result()
        good_arxiv = self._arxiv_citation_result()

        local_db.verify_reference.return_value = corrupt
        arxiv_citation.verify_reference.return_value = good_arxiv

        checker = self._make_checker(local_db=local_db, arxiv_citation=arxiv_citation)

        ref = self._deepseek_ref()
        paper_data, errors, url = checker.verify_reference(ref)

        # Local DB was tried first
        local_db.verify_reference.assert_called_once()
        # ArXiv citation was called as fallback
        arxiv_citation.verify_reference.assert_called_once()
        # Result should NOT have corrupt authors
        if paper_data and 'authors' in paper_data:
            author_names = [a.get('name', a) if isinstance(a, dict) else a
                           for a in paper_data['authors']]
            assert 'Adam Suma' not in author_names
            assert 'Sam Dauncey' not in author_names

    def test_has_major_author_discrepancy_detects_corrupt(self):
        """_has_major_author_discrepancy should detect zero author overlap."""
        checker = self._make_checker()
        errors = [{
            'error_type': 'author',
            'error_details': 'Author 1 mismatch\n       cited:  Daya Guo (not found in author list - et al case)\n       actual: Adam Suma, Sam Dauncey',
            'ref_authors_correct': 'Adam Suma, Sam Dauncey',
        }]
        assert checker._has_major_author_discrepancy(errors) is True

    def test_has_major_author_discrepancy_ignores_minor(self):
        """Normal author name variations should NOT trigger discrepancy."""
        checker = self._make_checker()
        # A case where the cited name is a slight variation of the actual
        errors = [{
            'error_type': 'author',
            'error_details': 'Author 1 mismatch\n       cited:  J. Smith (not found in author list - et al case)\n       actual: John Smith, Jane Doe',
            'ref_authors_correct': 'John Smith, Jane Doe',
        }]
        assert checker._has_major_author_discrepancy(errors) is False

    def test_has_major_author_discrepancy_no_author_errors(self):
        """No author errors should return False."""
        checker = self._make_checker()
        errors = [{
            'warning_type': 'venue',
            'warning_details': 'Venue mismatch',
        }]
        assert checker._has_major_author_discrepancy(errors) is False

    def test_non_arxiv_ref_uses_local_db_directly(self):
        """Non-ArXiv refs should use local DB without ArXiv fallback logic."""
        local_db = MagicMock()
        arxiv_citation = MagicMock()
        arxiv_citation.is_arxiv_reference.return_value = False

        good = self._good_local_db_result()
        local_db.verify_reference.return_value = good

        checker = self._make_checker(local_db=local_db, arxiv_citation=arxiv_citation)

        ref = {
            'title': 'Some Non-ArXiv Paper',
            'authors': ['John Smith'],
            'year': '2023',
            'url': '',
            'venue': 'NeurIPS',
        }
        paper_data, errors, url = checker.verify_reference(ref)

        local_db.verify_reference.assert_called_once()
        # No ArXiv fallback for non-ArXiv refs
        arxiv_citation.verify_reference.assert_not_called()


if __name__ == '__main__':
    unittest.main()
