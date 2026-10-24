from unittest.mock import Mock, patch

from refchecker.checkers.crossref import CrossRefReferenceChecker


WORK = {
    "DOI": "10.59350/z5v5d-mqf78",
    "type": "posted-content",
    "title": ["The XML Markup Evaluation Corpus"],
    "author": [{"given": "Alejandra", "family": "Casas Niño de Rivera"}],
    "published": {"date-parts": [[2016, 4, 18]]},
    "link": [{
        "URL": "https://pkp.sfu.ca/2016/04/18/the-xml-markup-evaluation-corpus/",
        "content-type": "text/html",
    }],
}


def _page_response(html):
    response = Mock()
    response.status_code = 200
    response.text = html
    response.content = html.encode("utf-8")
    return response


def test_primary_blog_page_can_confirm_cited_contact_author(monkeypatch):
    checker = CrossRefReferenceChecker()
    monkeypatch.setattr(checker, "search_works", lambda *args, **kwargs: [WORK])
    page = """
    <html><head><title>The XML Markup Evaluation Corpus</title></head>
    <body>
      <p>Please direct questions to Alex Garnett at
         <a href="mailto:garnett@sfu.ca">garnett at sfu.ca</a>.
      </p>
    </body></html>
    """

    with patch("refchecker.checkers.crossref.requests.get", return_value=_page_response(page)):
        verified_data, errors, url = checker.verify_reference({
            "title": "The XML Markup Evaluation Corpus",
            "authors": ["Garnett, A."],
            "year": 2016,
            "venue": "Public Knowledge Project",
            "url": "https://pkp.sfu.ca/2016/04/18/the-xml-markup-evaluation-corpus/",
        })

    assert verified_data is not None
    assert errors == []
    assert url == "https://doi.org/10.59350/z5v5d-mqf78"


def test_unrelated_cited_author_is_not_confirmed_by_primary_blog_page(monkeypatch):
    checker = CrossRefReferenceChecker()
    monkeypatch.setattr(checker, "search_works", lambda *args, **kwargs: [WORK])
    page = """
    <html><head><title>The XML Markup Evaluation Corpus</title></head>
    <body><p>Published by PKP Communications.</p></body></html>
    """

    with patch("refchecker.checkers.crossref.requests.get", return_value=_page_response(page)):
        verified_data, errors, _ = checker.verify_reference({
            "title": "The XML Markup Evaluation Corpus",
            "authors": ["Unrelated, U."],
            "year": 2016,
            "url": "https://pkp.sfu.ca/2016/04/18/the-xml-markup-evaluation-corpus/",
        })

    assert verified_data is not None
    assert any(error.get("error_type") == "author" for error in errors)
