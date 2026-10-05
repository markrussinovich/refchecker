from unittest.mock import Mock

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


def _response(html=SCINLP_PAGE):
    response = Mock()
    response.status_code = 200
    response.content = html.encode("utf-8")
    return response


def test_verifies_softcite_from_official_workshop_program(monkeypatch):
    checker = OfficialProceedingsChecker()
    monkeypatch.setattr(checker.session, "get", lambda *args, **kwargs: _response())

    data, errors, url = checker.verify_reference({
        "title": "Softcite: Automatic Extraction of Software Mentions in Research Literature",
        "authors": ["Du, Caifan", "Howison, James", "Lopez, Patrice"],
        "year": 2020,
        "venue": "Poster abstracts of the 1st Workshop on Natural Language Processing "
                 "and Data Mining for Scientific Text Workshop (SciNLP)",
    })

    assert data is not None
    assert data["_matched_database"] == "Official Workshop Program"
    assert errors == []
    assert url.endswith("softcite-automatic-extraction-of-software-mentions-in-research-literature.pdf")


def test_rejects_title_not_present_in_official_program(monkeypatch):
    checker = OfficialProceedingsChecker()
    monkeypatch.setattr(checker.session, "get", lambda *args, **kwargs: _response())

    data, errors, url = checker.verify_reference({
        "title": "A fabricated SciNLP poster",
        "authors": ["Du, Caifan"],
        "year": 2020,
        "venue": "SciNLP",
    })

    assert data is None
    assert errors == []
    assert url is None
