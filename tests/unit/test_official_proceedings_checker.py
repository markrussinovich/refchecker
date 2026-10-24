from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest
import requests

from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from refchecker.checkers.official_proceedings import OfficialProceedingsChecker

SCINLP_PAGE = """
<html><body><table>
  <tr><th>Poster Session</th><th>Title</th><th>Authors</th><th>Links</th></tr>
  <tr>
    <td>1</td>
    <td>Softcite: Automatic Extraction of Software Mentions in Research Literature</td>
    <td>Caifan Du, James Howison, Patrice Lopez</td>
    <td><a href="/history/2020/pdfs/softcite-automatic-extraction-of-software-mentions-in-research-literature.pdf">abs</a></td>
  </tr>
</table></body></html>
"""

USENIX_PROGRAM_URL = (
    "https://www.usenix.org/conference/usenixsecurity21/technical-sessions"
)
USENIX_PAPER_URL = (
    "https://www.usenix.org/conference/usenixsecurity21/presentation/aafer"
)
USENIX_TITLE = "Android SmartTVs Vulnerability Discovery via Log-Guided Fuzzing"
USENIX_AUTHORS = [
    "Yousra Aafer",
    "Wei You",
    "Yi Sun",
    "Yu Shi",
    "Xiangyu Zhang",
    "Heng Yin",
]
USENIX_PROGRAM = """
<html><body>
<h2><a href="/conference/usenixsecurity21/presentation/aafer">
Android SmartTVs Vulnerability Discovery via Log-Guided Fuzzing</a></h2>
<h2><a href="/conference/usenixsecurity21/presentation/other">
An Unrelated Paper About Browser Privacy</a></h2>
</body></html>
"""
USENIX_PAPER = """
<html><head>
<meta name="citation_title"
      content="Android {SmartTVs} Vulnerability Discovery via {Log-Guided} Fuzzing">
<meta name="citation_author" content="Yousra Aafer">
<meta name="citation_author" content="Wei You">
<meta name="citation_author" content="Yi Sun">
<meta name="citation_author" content="Yu Shi">
<meta name="citation_author" content="Xiangyu Zhang">
<meta name="citation_author" content="Heng Yin">
<meta name="citation_author_institution" content="University of Waterloo">
<meta name="citation_publication_date" content="2021">
<meta name="citation_conference_title"
      content="30th USENIX Security Symposium (USENIX Security 21)">
</head></html>
"""


def _usenix_reference(**overrides):
    reference = {
        "title": USENIX_TITLE,
        "authors": USENIX_AUTHORS[:],
        "year": 2021,
        "venue": "30th USENIX Security Symposium",
    }
    reference.update(overrides)
    return reference


def _response(html=SCINLP_PAGE):
    response = Mock()
    response.status_code = 200
    response.content = html.encode("utf-8")
    return response


@pytest.fixture
def usenix_checker(monkeypatch):
    monkeypatch.setattr(OfficialProceedingsChecker, "_USENIX_REQUEST_INTERVAL", 0)
    checker = OfficialProceedingsChecker()
    pages = {
        USENIX_PROGRAM_URL: USENIX_PROGRAM,
        USENIX_PAPER_URL: USENIX_PAPER,
    }
    checker.session.get = Mock(side_effect=lambda url, **kwargs: _response(pages[url]))
    return checker


def test_verifies_softcite_from_official_workshop_program(monkeypatch):
    checker = OfficialProceedingsChecker()
    monkeypatch.setattr(checker.session, "get", lambda *args, **kwargs: _response())

    data, errors, url = checker.verify_reference(
        {
            "title": "Softcite: Automatic Extraction of Software Mentions in Research Literature",
            "authors": ["Du, Caifan", "Howison, James", "Lopez, Patrice"],
            "year": 2020,
            "venue": "Poster abstracts of the 1st Workshop on Natural Language Processing "
            "and Data Mining for Scientific Text Workshop (SciNLP)",
        }
    )

    assert data is not None
    assert data["_matched_database"] == "Official Workshop Program"
    assert errors == []
    assert url.endswith(
        "softcite-automatic-extraction-of-software-mentions-in-research-literature.pdf"
    )


def test_rejects_title_not_present_in_official_program(monkeypatch):
    checker = OfficialProceedingsChecker()
    monkeypatch.setattr(checker.session, "get", lambda *args, **kwargs: _response())

    data, errors, url = checker.verify_reference(
        {
            "title": "A fabricated SciNLP poster",
            "authors": ["Du, Caifan"],
            "year": 2020,
            "venue": "SciNLP",
        }
    )

    assert data is None
    assert errors == []
    assert url is None


@pytest.mark.parametrize(
    "field,venue",
    [
        ("venue", "34th USENIX Security Symposium"),
        ("booktitle", "Proceedings of the {USENIX} Security Symposium"),
        ("journal", "USENIX-Security"),
        ("raw_text", "34th Security Symposium (USENIX)"),
    ],
)
def test_recognizes_usenix_venue_variants(field, venue):
    checker = OfficialProceedingsChecker()
    assert checker._program_url({field: venue, "year": "2025"}) == (
        "https://www.usenix.org/conference/usenixsecurity25/technical-sessions"
    )


def test_discovers_usenix_paper_and_reads_authoritative_metadata(usenix_checker):
    data, errors, url = usenix_checker.verify_reference(_usenix_reference())

    assert errors == []
    assert url == USENIX_PAPER_URL
    assert data["title"] == USENIX_TITLE
    assert data["authors"] == USENIX_AUTHORS
    assert data["year"] == 2021
    assert data["venue"] == "30th USENIX Security Symposium (USENIX Security 21)"
    assert data["_matched_database"] == "USENIX"
    assert usenix_checker.session.get.call_count == 2


@pytest.mark.parametrize("field", ["url", "cited_url"])
def test_direct_usenix_url_works_without_venue_or_year(usenix_checker, field):
    data, errors, url = usenix_checker.verify_reference(
        _usenix_reference(venue=None, year=None, **{field: USENIX_PAPER_URL})
    )
    assert data["year"] == 2021
    assert errors == []
    assert url == USENIX_PAPER_URL
    usenix_checker.session.get.assert_called_once_with(
        USENIX_PAPER_URL,
        timeout=usenix_checker.timeout,
    )


def test_reports_author_discrepancy_instead_of_discarding_match(usenix_checker):
    data, errors, _ = usenix_checker.verify_reference(
        _usenix_reference(authors=["Yousra Aafer", "Invented Author"])
    )
    assert data["authors"] == USENIX_AUTHORS
    assert errors[0]["error_type"] == "author"
    assert errors[0]["ref_authors_correct"] == ", ".join(USENIX_AUTHORS)


def test_direct_url_reports_wrong_title_and_year(usenix_checker):
    data, errors, _ = usenix_checker.verify_reference(
        _usenix_reference(
            title="An entirely different paper",
            year=2024,
            url=USENIX_PAPER_URL,
        )
    )
    assert data["title"] == USENIX_TITLE
    assert {e.get("error_type") or e.get("warning_type") for e in errors} == {
        "title",
        "year",
    }
    assert errors[0]["ref_title_correct"] == USENIX_TITLE
    assert errors[1]["ref_year_correct"] == 2021


def test_discovery_reports_near_title_match_with_matching_authors(usenix_checker):
    data, errors, _ = usenix_checker.verify_reference(
        _usenix_reference(
            title=USENIX_TITLE.replace(" via ", " "),
        )
    )
    assert data is not None
    assert errors[0]["error_type"] == "title"
    assert errors[0]["ref_title_correct"] == USENIX_TITLE


def test_rejects_near_title_match_with_unrelated_authors(usenix_checker):
    data, errors, url = usenix_checker.verify_reference(
        _usenix_reference(
            title=USENIX_TITLE.replace(" via ", " "),
            authors=["Invented Author"],
        )
    )
    assert (data, errors, url) == (None, [], None)


def test_rejects_fabricated_usenix_title(usenix_checker):
    assert usenix_checker.verify_reference(
        _usenix_reference(title="Imaginary Quantum Penguins on Mars")
    ) == (None, [], None)
    usenix_checker.session.get.assert_called_once()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.usenix.org.evil.example/conference/usenixsecurity21/presentation/aafer",
        "https://evil.example/conference/usenixsecurity21/presentation/aafer",
        "https://www.usenix.org/conference/osdi21/presentation/aafer",
        "http://[invalid",
    ],
)
def test_does_not_fetch_unrelated_or_malformed_urls(usenix_checker, url):
    assert usenix_checker.verify_reference(
        _usenix_reference(venue="", year=None, url=url)
    ) == (None, [], None)
    usenix_checker.session.get.assert_not_called()


def test_caches_pages_across_concurrent_references(usenix_checker):
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                usenix_checker.verify_reference,
                [_usenix_reference() for _ in range(4)],
            )
        )
    assert all(result == results[0] for result in results)
    assert usenix_checker.session.get.call_count == 2


def test_reuses_persistent_page_cache(usenix_checker, tmp_path):
    usenix_checker.cache_dir = str(tmp_path)
    expected = usenix_checker.verify_reference(_usenix_reference())
    other = OfficialProceedingsChecker()
    other.cache_dir = str(tmp_path)
    other.session.get = Mock(side_effect=AssertionError("Unexpected network call"))
    assert other.verify_reference(_usenix_reference()) == expected


def test_honors_usenix_crawl_delay(usenix_checker, monkeypatch):
    monkeypatch.setattr(OfficialProceedingsChecker, "_USENIX_REQUEST_INTERVAL", 10)
    monkeypatch.setattr(OfficialProceedingsChecker, "_usenix_last_request", 0)
    with patch("refchecker.checkers.official_proceedings.time") as clock:
        clock.monotonic.side_effect = [100, 100, 100, 110]
        data, errors, _ = usenix_checker.verify_reference(_usenix_reference())
    assert data is not None
    assert errors == []
    clock.sleep.assert_called_once_with(10)


@pytest.mark.parametrize(
    "failure",
    [
        requests.Timeout("timed out"),
        requests.HTTPError("503 Service Unavailable"),
    ],
)
def test_surfaces_request_failures_and_does_not_cache_them(usenix_checker, failure):
    usenix_checker.session.get.side_effect = failure
    for _ in range(2):
        data, errors, _ = usenix_checker.verify_reference(_usenix_reference())
        assert data is None
        assert errors[0]["error_type"] == "api_failure"
        assert str(failure) in errors[0]["error_details"]
    assert usenix_checker.session.get.call_count == 2


def test_missing_metadata_is_a_checker_failure_not_verified(usenix_checker):
    usenix_checker.session.get.side_effect = lambda *a, **kw: _response("<html/>")
    data, errors, _ = usenix_checker.verify_reference(
        _usenix_reference(url=USENIX_PAPER_URL)
    )
    assert data is None
    assert errors[0]["error_type"] == "api_failure"
    assert "missing citation metadata" in errors[0]["error_details"]


def _hybrid_with_usenix(proceedings):
    with patch.object(
        EnhancedHybridReferenceChecker, "_initialize_checker", return_value=None
    ):
        hybrid = EnhancedHybridReferenceChecker(enable_arxiv_citation=False)
    hybrid.official_proceedings = proceedings
    return hybrid


def test_usenix_precedes_incomplete_database_metadata(usenix_checker, monkeypatch):
    hybrid = _hybrid_with_usenix(usenix_checker)
    incomplete = ({"title": USENIX_TITLE, "authors": []}, [], None)
    monkeypatch.setattr(
        hybrid,
        "_verify_non_arxiv_parallel",
        lambda *a, **kw: (None, {"crossref": incomplete}),
    )
    data, errors, url = hybrid.verify_reference(_usenix_reference())
    assert data["_matched_database"] == "USENIX"
    assert data["authors"] == USENIX_AUTHORS
    assert errors == []
    assert url == USENIX_PAPER_URL


def test_usenix_failure_is_preserved_in_unverified_reason(usenix_checker):
    hybrid = _hybrid_with_usenix(usenix_checker)
    usenix_checker.session.get.side_effect = requests.Timeout("USENIX timed out")
    data, errors, _ = hybrid.verify_reference(_usenix_reference())
    assert data is None
    assert errors[0]["error_type"] == "unverified"
    assert "USENIX timed out" in errors[0]["error_details"]
    assert errors[0]["sources_negative"] == 0


def test_usenix_results_match_cli_and_webui(usenix_checker):
    from backend.refchecker_wrapper import ProgressRefChecker
    from refchecker.core.refchecker import ArxivReferenceChecker

    hybrid = _hybrid_with_usenix(usenix_checker)
    cli = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    cli.non_arxiv_checker = hybrid
    cli.verify_github_reference = lambda ref: None
    cli.verify_webpage_reference = lambda ref: None
    web = ProgressRefChecker.__new__(ProgressRefChecker)
    web.checker = hybrid
    web.check_id = None
    reference = _usenix_reference(authors=["Yousra Aafer", "Invented Author"])

    cli_errors, cli_url, cli_data = cli.verify_reference_standard(None, dict(reference))
    bulk_errors, bulk_url, bulk_data = cli.verify_reference(None, dict(reference))
    web_data, web_errors, web_url = web._verify_reference(dict(reference))

    assert (cli_data, cli_errors, cli_url) == (web_data, web_errors, web_url)
    assert (bulk_data, bulk_errors, bulk_url) == (web_data, web_errors, web_url)
    assert cli_data["_matched_database"] == "USENIX"
    assert cli_errors[0]["error_type"] == "author"
