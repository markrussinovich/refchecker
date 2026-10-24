from unittest.mock import Mock

from refchecker.checkers.institutional_reports import InstitutionalReportsChecker


INDEX_HTML = """
<html><body><table>
  <tr>
    <td>348</td>
    <td>Kong, A.</td>
    <td>August 1992</td>
    <td><a href="https://example.edu/tr348.pdf">
      A note on importance sampling using standardized weights
    </a></td>
  </tr>
</table></body></html>
"""


def _response():
    response = Mock()
    response.status_code = 200
    response.content = INDEX_HTML.encode("utf-8")
    return response


def test_verifies_uchicago_technical_report_from_official_index(monkeypatch):
    checker = InstitutionalReportsChecker()
    monkeypatch.setattr(checker.session, "get", lambda *args, **kwargs: _response())

    data, errors, url = checker.verify_reference({
        "title": "A note on importance sampling using standardized weights",
        "authors": ["Kong, Augustine"],
        "year": 1992,
        "journal": "University of Chicago, Dept. of Statistics, Tech. Rep",
        "volume": "348",
    })

    assert data is not None
    assert data["_matched_database"] == "Official Institutional Report Index"
    assert errors == []
    assert url == "https://example.edu/tr348.pdf"


def test_rejects_wrong_report_number(monkeypatch):
    checker = InstitutionalReportsChecker()
    monkeypatch.setattr(checker.session, "get", lambda *args, **kwargs: _response())

    data, errors, url = checker.verify_reference({
        "title": "A note on importance sampling using standardized weights",
        "authors": ["Kong, Augustine"],
        "year": 1992,
        "journal": "University of Chicago, Dept. of Statistics, Tech. Rep",
        "volume": "999",
    })

    assert data is None
    assert errors == []
    assert url is None
