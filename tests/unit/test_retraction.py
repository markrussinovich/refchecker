"""Unit tests for the retraction signal (OpenAlex is_retracted, no fabrication)."""

from backend import retraction


def _refs():
    return [
        {"index": 1, "title": "Retracted study", "doi": "10.1000/retracted"},
        {"index": 2, "title": "Clean study", "doi": "https://doi.org/10.1000/clean"},
        {"index": 3, "title": "No DOI study", "authors": []},
        {"index": 4, "title": "Unknown-to-openalex", "doi": "10.9999/notfound"},
    ]


def _fake_fetch(dois):
    # Simulates OpenAlex: only knows about two of the DOIs.
    db = {
        "10.1000/retracted": {"is_retracted": True, "title": "Retracted study (OA)"},
        "10.1000/clean": {"is_retracted": False, "title": "Clean study (OA)"},
    }
    return {d: db[d] for d in dois if d in db}


def test_normalize_doi_variants():
    assert retraction.normalize_doi("https://doi.org/10.1000/abc") == "10.1000/abc"
    assert retraction.normalize_doi("doi:10.1000/abc") == "10.1000/abc"
    assert retraction.normalize_doi("10.1000/abc.") == "10.1000/abc"
    assert retraction.normalize_doi("not a doi") is None
    assert retraction.normalize_doi(None) is None


def test_flags_only_real_retractions():
    res = retraction.check_retractions(_refs(), fetch=_fake_fetch)
    by_idx = {r["index"]: r for r in res["results"]}
    assert by_idx[1]["status"] == "retracted"
    assert by_idx[2]["status"] == "clean"
    assert by_idx[3]["status"] == "no_doi"
    assert by_idx[4]["status"] == "unknown"
    assert res["retracted"] == 1
    assert res["with_doi"] == 3
    assert res["source"] == "openalex"


def test_no_fabrication_when_fetch_empty():
    # If the source returns nothing, NOTHING is flagged retracted.
    res = retraction.check_retractions(_refs(), fetch=lambda dois: {})
    assert res["retracted"] == 0
    assert all(r["status"] in ("no_doi", "unknown") for r in res["results"])


def test_handles_non_list_and_non_dict():
    assert retraction.check_retractions(None, fetch=_fake_fetch)["checked"] == 0
    res = retraction.check_retractions([{"index": 1, "doi": "10.1000/retracted"}, "garbage"], fetch=_fake_fetch)
    assert res["retracted"] == 1
    assert res["checked"] == 1
