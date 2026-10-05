from unittest.mock import Mock

from refchecker.checkers.openalex import OpenAlexReferenceChecker


def test_openalex_search_uses_current_select_fields(monkeypatch):
    checker = OpenAlexReferenceChecker()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"results": []}
    response.raise_for_status.return_value = None

    def fake_get(_url, *, params, **_kwargs):
        assert "grants" not in params["select"].split(",")
        return response

    monkeypatch.setattr("refchecker.checkers.openalex.requests.get", fake_get)

    assert checker._search_works_uncached("Test paper", 2024) == []


def test_openalex_exact_title_recovers_culicover_record(monkeypatch):
    checker = OpenAlexReferenceChecker()
    work = {
        "id": "https://openalex.org/W2621351960",
        "doi": None,
        "title": "Paraphrase generation and information retrieval from stored text.",
        "display_name": "Paraphrase generation and information retrieval from stored text.",
        "publication_year": 1968,
        "authorships": [{
            "author": {"display_name": "Peter W. Culicover"},
        }],
        "primary_location": {
            "landing_page_url": "https://www.mt-archive.info/MT-1968-Culicover.pdf",
        },
        "open_access": {"is_oa": False},
        "locations": [],
        "ids": {"openalex": "https://openalex.org/W2621351960"},
    }
    monkeypatch.setattr(checker, "search_works", lambda *_args, **_kwargs: [work])

    data, errors, url = checker.verify_reference({
        "title": "Paraphrase generation and information retrieval from stored text",
        "authors": ["Culicover, Peter W."],
        "year": 1968,
        "venue": "Mech. Transl. Comput. Linguistics",
    })

    assert data is not None
    assert errors == []
    assert url == "https://www.mt-archive.info/MT-1968-Culicover.pdf"
