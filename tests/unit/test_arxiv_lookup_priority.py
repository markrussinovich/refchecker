"""
Regression test: ArXiv ID direct lookup must run BEFORE title matching.

When a reference has an ArXiv URL, the checker should resolve it via
get_paper_by_arxiv_id() first.  Title matching (match_paper_by_title /
search_paper) should only be attempted if the ArXiv lookup fails or
returns a title mismatch.

This prevents corrupt / duplicate Semantic Scholar entries (found via
title match) from shadowing the authoritative ArXiv-ID-based entry.
See: DeepSeek-R1 CorpusID:284488789 incident.
"""

import unittest
from unittest.mock import patch, MagicMock, call
from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker


class TestArxivLookupPriority(unittest.TestCase):
    """Ensure ArXiv ID lookup runs before title matching."""

    def setUp(self):
        self.checker = NonArxivReferenceChecker()
        # Avoid real HTTP calls
        self.checker.session = MagicMock()
        self.checker.request_delay = 0

    # -- helpers ----------------------------------------------------------

    def _good_paper(self, title="DeepSeek-R1", arxiv_id="2501.12948"):
        """Return a well-formed S2 paper dict (the *correct* entry)."""
        return {
            "paperId": "correct_id",
            "title": title,
            "authors": [{"name": "Daya Guo"}, {"name": "Dejian Yang"}],
            "year": 2025,
            "venue": "arXiv",
            "externalIds": {"ArXiv": arxiv_id},
        }

    def _corrupt_paper(self, title="DeepSeek-R1"):
        """Return a corrupt S2 entry (wrong authors, same title)."""
        return {
            "paperId": "corrupt_id",
            "title": title,
            "authors": [{"name": "Adam Suma"}, {"name": "Sam Dauncey"}],
            "year": 2025,
            "venue": "",
            "externalIds": {},
        }

    def _reference(self, title="DeepSeek-R1", url="https://arxiv.org/abs/2501.12948",
                    raw_text=""):
        return {
            "title": title,
            "authors": ["Daya Guo", "Dejian Yang"],
            "year": "2025",
            "url": url,
            "raw_text": raw_text,
        }

    # -- tests ------------------------------------------------------------

    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    @patch.object(NonArxivReferenceChecker, "search_paper")
    @patch.object(NonArxivReferenceChecker, "get_paper_by_arxiv_id")
    @patch.object(NonArxivReferenceChecker, "get_paper_by_doi", return_value=None)
    def test_arxiv_lookup_runs_before_title_match(
        self, _doi, mock_arxiv, mock_search, mock_match
    ):
        """ArXiv ID lookup must be attempted before title matching."""
        good = self._good_paper()
        mock_arxiv.return_value = good
        mock_match.return_value = self._corrupt_paper()

        ref = self._reference()
        result = self.checker.verify_reference(ref)

        # ArXiv lookup was called
        mock_arxiv.assert_called_once_with("2501.12948")

        # Title match / search should NOT have been called because
        # the ArXiv lookup already succeeded with a matching title.
        mock_match.assert_not_called()
        mock_search.assert_not_called()

    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    @patch.object(NonArxivReferenceChecker, "search_paper")
    @patch.object(NonArxivReferenceChecker, "get_paper_by_arxiv_id")
    @patch.object(NonArxivReferenceChecker, "get_paper_by_doi", return_value=None)
    def test_arxiv_lookup_uses_correct_entry_over_corrupt(
        self, _doi, mock_arxiv, mock_search, mock_match
    ):
        """The result should come from the ArXiv lookup, not a corrupt title match."""
        good = self._good_paper()
        corrupt = self._corrupt_paper()
        mock_arxiv.return_value = good
        mock_match.return_value = corrupt

        ref = self._reference()
        paper_data, errors, paper_url = self.checker.verify_reference(ref)

        # The returned paper should be the correct one from ArXiv lookup
        self.assertEqual(paper_data["paperId"], "correct_id")
        self.assertNotEqual(paper_data.get("paperId"), "corrupt_id")

    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    @patch.object(NonArxivReferenceChecker, "search_paper", return_value=[])
    @patch.object(NonArxivReferenceChecker, "get_paper_by_arxiv_id", return_value=None)
    @patch.object(NonArxivReferenceChecker, "get_paper_by_doi", return_value=None)
    def test_title_match_used_when_arxiv_lookup_fails(
        self, _doi, mock_arxiv, mock_search, mock_match
    ):
        """When ArXiv lookup returns nothing, title match should be tried."""
        good = self._good_paper()
        mock_match.return_value = good

        ref = self._reference()
        result = self.checker.verify_reference(ref)

        # ArXiv lookup was attempted first
        mock_arxiv.assert_called_once()
        # Then title match was used as fallback
        mock_match.assert_called_once()

    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    @patch.object(NonArxivReferenceChecker, "search_paper", return_value=[])
    @patch.object(NonArxivReferenceChecker, "get_paper_by_arxiv_id")
    @patch.object(NonArxivReferenceChecker, "get_paper_by_doi", return_value=None)
    def test_no_arxiv_url_skips_arxiv_lookup(
        self, _doi, mock_arxiv, mock_search, mock_match
    ):
        """References without an ArXiv URL should not trigger ArXiv ID lookup."""
        good = self._good_paper()
        mock_match.return_value = good

        ref = self._reference(url="https://doi.org/10.1000/example")
        result = self.checker.verify_reference(ref)

        mock_arxiv.assert_not_called()
        mock_match.assert_called_once()

    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    @patch.object(NonArxivReferenceChecker, "search_paper", return_value=[])
    @patch.object(NonArxivReferenceChecker, "get_paper_by_arxiv_id")
    @patch.object(NonArxivReferenceChecker, "get_paper_by_doi", return_value=None)
    def test_arxiv_pdf_url_also_triggers_arxiv_lookup(
        self, _doi, mock_arxiv, mock_search, mock_match
    ):
        """ArXiv PDF URLs (arxiv.org/pdf/...) should also trigger direct lookup."""
        good = self._good_paper()
        mock_arxiv.return_value = good

        ref = self._reference(url="https://arxiv.org/pdf/2501.12948")
        result = self.checker.verify_reference(ref)

        mock_arxiv.assert_called_once_with("2501.12948")
        mock_match.assert_not_called()

    @patch.object(NonArxivReferenceChecker, "match_paper_by_title")
    @patch.object(NonArxivReferenceChecker, "search_paper", return_value=[])
    @patch.object(NonArxivReferenceChecker, "get_paper_by_arxiv_id")
    @patch.object(NonArxivReferenceChecker, "get_paper_by_doi", return_value=None)
    def test_arxiv_id_in_venue_triggers_direct_lookup(
        self, _doi, mock_arxiv, mock_search, mock_match
    ):
        """ArXiv ID in venue/raw_text (no URL) should trigger direct lookup.

        This is the DeepSeek-R1 scenario: the reference has no URL field,
        but has 'arXiv preprint arXiv:2501.12948' in venue/raw_text.
        """
        good = self._good_paper()
        mock_arxiv.return_value = good

        ref = self._reference(
            url="",
            raw_text="Daya Guo*et al#Deepseek-r1: Incentivizing reasoning "
                     "capability in llms via reinforcement learning#"
                     "arXiv preprint arXiv:2501.12948#2025#",
        )
        result = self.checker.verify_reference(ref)

        mock_arxiv.assert_called_once_with("2501.12948")
        mock_match.assert_not_called()


if __name__ == "__main__":
    unittest.main()
