"""Missing venue is a warning, not an error.

Omitting the venue is an incompleteness issue, not a factual mistake: citing a
paper by its preprint (which has no venue) is normal scholarly practice. A
*wrong* venue is already reported as a warning, so reporting a *missing* venue
as a hard error was inconsistent as well as too strict.

Both Semantic Scholar checkers (online API and local database) must agree, so
that the bulk, CLI and WebUI paths report identical counts.
"""

import pytest

from refchecker.utils.error_utils import create_venue_warning


PAPER = {
    "paperId": "abc123",
    "title": "Deep Residual Learning for Image Recognition",
    "year": 2016,
    "authors": [{"authorId": "1", "name": "Kaiming He"}],
    "venue": "Computer Vision and Pattern Recognition",
    "externalIds": {"DOI": "10.1109/CVPR.2016.90"},
}

REFERENCE_WITHOUT_VENUE = {
    "title": "Deep Residual Learning for Image Recognition",
    "authors": ["Kaiming He"],
    "year": 2016,
    "doi": "10.1109/CVPR.2016.90",
}


def _venue_issues(issues):
    return [i for i in issues if i.get("error_type") == "venue" or i.get("warning_type") == "venue"]


class TestCreateVenueWarning:
    def test_missing_venue_is_warning(self):
        issue = create_venue_warning("", "Computer Vision and Pattern Recognition")
        assert issue["warning_type"] == "venue"
        assert "error_type" not in issue
        assert "Missing venue" in issue["warning_details"]

    def test_cited_venue_that_cleans_to_empty_is_warning(self):
        # "Proceedings of the" carries no information once cleaned
        issue = create_venue_warning("Proceedings of the", "Nature")
        assert issue["warning_type"] == "venue"
        assert "error_type" not in issue

    def test_venue_mismatch_remains_a_warning(self):
        issue = create_venue_warning("NeurIPS", "Computer Vision and Pattern Recognition")
        assert issue["warning_type"] == "venue"
        assert "error_type" not in issue

    def test_correct_venue_is_carried_for_correction(self):
        # The corrected-reference builder relies on this key regardless of severity
        issue = create_venue_warning("", "Nature")
        assert issue["ref_venue_correct"] == "Nature"


class TestOnlineSemanticScholarChecker:
    def test_missing_venue_reported_as_warning(self, monkeypatch):
        from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker

        checker = NonArxivReferenceChecker()
        monkeypatch.setattr(checker, "get_paper_by_doi", lambda doi: dict(PAPER))

        verified_data, issues, _url = checker.verify_reference(dict(REFERENCE_WITHOUT_VENUE))

        assert verified_data is not None
        venue_issues = _venue_issues(issues)
        assert venue_issues, f"Expected a missing-venue issue, got: {issues}"
        assert all("error_type" not in i for i in venue_issues), f"Missing venue must not be an error: {issues}"
        assert any("should include" in i["warning_details"] for i in venue_issues)

    def test_generic_preprint_venue_still_reports_nothing(self, monkeypatch):
        from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker

        paper = dict(PAPER)
        paper["venue"] = "ArXiv"
        checker = NonArxivReferenceChecker()
        monkeypatch.setattr(checker, "get_paper_by_doi", lambda doi: paper)

        _verified, issues, _url = checker.verify_reference(dict(REFERENCE_WITHOUT_VENUE))
        assert not _venue_issues(issues), f"Generic preprint venue must not be reported: {issues}"


class TestPathParity:
    """Both checkers must classify a missing venue the same way."""

    def test_no_checker_emits_a_missing_venue_error(self):
        import inspect

        from refchecker.checkers import local_semantic_scholar, semantic_scholar

        for module in (local_semantic_scholar, semantic_scholar):
            source = inspect.getsource(module)
            idx = source.find("Venue missing: should include")
            assert idx != -1, f"{module.__name__} no longer emits a missing-venue issue"
            # The dict literal opens on the line above the message
            preceding = source[max(0, idx - 200):idx]
            assert "'warning_type': 'venue'" in preceding, (
                f"{module.__name__} reports a missing venue as an error; it must be a warning"
            )
