import ast
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.database import Database
from backend.usage_tracking import infer_paper_identity
from refchecker.utils import paper_metadata


TITLE = "A Study of Reliable Systems"


def _work(name="Jane Doe", author_id="A123", title=TITLE):
    return {
        "title": title, "publication_year": 2025,
        "authorships": [{
            "author": {
                "display_name": name, "id": f"https://openalex.org/{author_id}",
                "orcid": "https://orcid.org/0000-0002-1825-0097",
            },
            "institutions": [{"display_name": "Example University"}],
        }],
    }


@pytest.fixture
def clients(monkeypatch):
    oa, s2 = MagicMock(), MagicMock()
    oa.get_work_by_doi.return_value = None
    oa.search_works.return_value = []
    s2.get_paper_by_arxiv_id.return_value = None
    s2.get_paper_by_doi.return_value = None
    monkeypatch.setattr(paper_metadata, "OpenAlexReferenceChecker", lambda: oa)
    monkeypatch.setattr(paper_metadata, "NonArxivReferenceChecker", lambda **_kw: s2)
    monkeypatch.setattr(paper_metadata, "get_arxiv_paper_by_id", lambda _id: None)
    return oa, s2


def test_exact_title_uses_shared_author_enrichment(clients):
    oa, s2 = clients
    oa.search_works.return_value = [_work(title="A Study of Reliable Systems!")]
    result = paper_metadata.resolve_paper_authors(TITLE, cache_dir="cache")
    assert result["available"]
    assert result["source"] == "openalex"
    assert result["authors"] == [{
        "name": "Jane Doe", "openalex_id": "A123",
        "orcid": "0000-0002-1825-0097", "institutions": ["Example University"],
    }]
    assert result["year"] == 2025
    assert oa.cache_dir == "cache"
    s2.get_paper_by_arxiv_id.assert_not_called()


def test_doi_precedes_title_search(clients):
    oa, _ = clients
    oa.get_work_by_doi.return_value = _work()
    result = paper_metadata.resolve_paper_authors("A filename, not a title", doi="10.1234/test")
    assert result["available"]
    oa.get_work_by_doi.assert_called_once_with("10.1234/test")
    oa.search_works.assert_not_called()


def test_arxiv_identifier_precedes_same_title_work(clients):
    oa, s2 = clients
    s2.get_paper_by_arxiv_id.return_value = {
        "title": TITLE, "year": 2024, "authors": [{"name": "John Smith", "authorId": "123"}],
    }
    oa.search_works.return_value = [_work()]
    result = paper_metadata.resolve_paper_authors(TITLE, arxiv_id="2501.12345")
    assert result["authors"] == [{"name": "John Smith", "s2_author_id": "123"}]
    assert result["source"] == "semantic_scholar"
    oa.search_works.assert_not_called()
    s2._session.close.assert_called_once()


def test_native_arxiv_authors_survive_index_rate_limits(clients, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    paper = SimpleNamespace(
        title=TITLE, published=datetime(2025, 1, 1),
        authors=[SimpleNamespace(name="Jane Doe")],
    )
    monkeypatch.setattr(paper_metadata, "get_arxiv_paper_by_id", lambda _id: paper)
    result = paper_metadata.resolve_paper_authors(TITLE, arxiv_id="2501.12345")
    assert result["source"] == "arxiv"
    assert result["authors"] == [{"name": "Jane Doe"}]
    assert result["year"] == 2025
    clients[0].search_works.assert_not_called()


@pytest.mark.parametrize("works", [
    [_work(title=TITLE + " with Different Methods")],
    [_work(), _work(name="Other Person", author_id="A456")],
    [],
])
def test_abstains_on_wrong_or_ambiguous_title(clients, works):
    clients[0].search_works.return_value = works
    result = paper_metadata.resolve_paper_authors(TITLE)
    assert not result["available"]
    assert result["authors"] == []
    assert result["reason"]


def test_duplicate_records_with_same_authors_are_safe(clients):
    clients[0].search_works.return_value = [_work(), _work()]
    assert paper_metadata.resolve_paper_authors(TITLE)["available"]


def test_doi_falls_back_to_s2(clients):
    _, s2 = clients
    s2.get_paper_by_doi.return_value = {
        "title": TITLE, "authors": [{"name": "Jane Doe", "authorId": "123"}],
    }
    assert paper_metadata.resolve_paper_authors("", doi="10.1234/test")["available"]


def test_placeholder_title_does_not_search(clients):
    assert not paper_metadata.resolve_paper_authors("Pasted Text")["available"]
    clients[0].search_works.assert_not_called()


def test_paper_metadata_persists_without_changing_reference_results(tmp_path):
    async def scenario():
        database = Database(str(tmp_path / "history.db"))
        await database.init_db()
        check_id = await database.create_pending_check(TITLE, "2501.12345", "url")
        before = await database.get_check_by_id(check_id)
        metadata = {
            "available": True, "profiles_fetched_at": time.time(),
            "authors": [{
                "name": "Jane Doe", "openalex_id": "A123",
                "profile_lookup_complete": True,
                "profile": {"available": True, "hIndex": 12, "citationCount": 456},
            }],
        }
        assert await database.update_check_paper_metadata(check_id, metadata)
        await database.update_check_label(check_id, "My custom label")
        # A fresh instance must recover the metadata from disk.
        after = await Database(database.db_path).get_check_by_id(check_id)
        assert after["paper_metadata"] == metadata
        for key in ("results_json", "total_refs", "errors_count", "warnings_count", "unverified_count"):
            assert before[key] == after[key]
        assert not await database.update_check_paper_metadata(check_id + 1, metadata)
    asyncio.run(scenario())


def _endpoint_namespace(check):
    # As in test_author_profile.py, lift the shipped route without initializing
    # the app's global services or accessing the user's local database.
    path = Path(__file__).resolve().parents[2] / "backend" / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    route = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "paper_authors")
    route.decorator_list = []
    module = ast.Module(body=[route], type_ignores=[])
    ns = {
        "asyncio": asyncio, "HTTPException": HTTPException, "Depends": lambda _: None,
        "UserInfo": object, "require_user": None,
        "_get_owned_check_or_404": AsyncMock(return_value=check),
        "_get_configured_cache_dir": AsyncMock(return_value="cache"),
        "_resolve_semantic_scholar_api_key": AsyncMock(return_value=None),
        "infer_paper_identity": infer_paper_identity,
        "db": MagicMock(update_check_paper_metadata=AsyncMock(return_value=True)),
        "logger": MagicMock(),
        "_AUTHOR_PROFILE_TTL": 6 * 60 * 60,
        "_preload_paper_author_profiles": AsyncMock(side_effect=lambda metadata, _user: metadata),
    }
    exec(compile(module, str(path), "exec"), ns)
    return ns


def test_endpoint_returns_persisted_authors_without_network(monkeypatch):
    metadata = {"available": True, "authors": [{"name": "Jane Doe"}], "profiles_fetched_at": time.time()}
    ns = _endpoint_namespace({"paper_metadata": metadata})
    resolver = MagicMock()
    monkeypatch.setattr(paper_metadata, "resolve_paper_authors", resolver)
    assert asyncio.run(ns["paper_authors"](42, object())) == metadata
    ns["_get_owned_check_or_404"].assert_awaited_once()
    resolver.assert_not_called()
    ns["_preload_paper_author_profiles"].assert_not_awaited()


def test_endpoint_upgrades_legacy_metadata_and_refreshes_expired_profiles(monkeypatch):
    for timestamp in (None, time.time() - 7 * 60 * 60):
        metadata = {"available": True, "authors": [{"name": "Jane Doe"}], "title": TITLE}
        if timestamp is not None:
            metadata["profiles_fetched_at"] = timestamp
        ns = _endpoint_namespace({"paper_metadata": metadata})
        resolver = MagicMock()
        monkeypatch.setattr(paper_metadata, "resolve_paper_authors", resolver)
        asyncio.run(ns["paper_authors"](42, object()))
        resolver.assert_not_called()
        ns["_preload_paper_author_profiles"].assert_awaited_once()
        ns["db"].update_check_paper_metadata.assert_awaited_once()


def _preload_namespace(profile_api, find_api):
    from types import SimpleNamespace
    path = Path(__file__).resolve().parents[2] / "backend" / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    helper = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_preload_paper_author_profiles")
    ns = {
        "asyncio": asyncio, "UserInfo": object, "logger": MagicMock(),
        "author_profile": profile_api, "author_find": find_api,
        "_AuthorProfileRequest": SimpleNamespace, "_AuthorFindRequest": SimpleNamespace,
        "_merge_author_profiles": lambda primary, secondary: {**(primary or {}), **secondary},
    }
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(path), "exec"), ns)
    return ns


def test_preload_profiles_uses_existing_apis_and_preserves_author_order():
    profile_api = AsyncMock(return_value={"available": True, "hIndex": 12, "orcid": "known"})
    find_api = AsyncMock(return_value={
        "available": True, "openalex_id": "A222", "citationCount": 456, "orcid": "found",
    })
    ns = _preload_namespace(profile_api, find_api)
    metadata = {
        "title": TITLE, "year": 2025,
        "authors": [{"name": "First", "openalex_id": "A111"}, {"name": "Second"}],
    }
    result = asyncio.run(ns["_preload_paper_author_profiles"](metadata, object()))
    assert [a["name"] for a in result["authors"]] == ["First", "Second"]
    assert result["authors"][0]["profile"]["hIndex"] == 12
    assert result["authors"][1]["openalex_id"] == "A222"
    assert result["authors"][1]["profile"]["citationCount"] == 456
    assert all(a["profile_lookup_complete"] for a in result["authors"])
    assert result["profiles_fetched_at"] <= time.time()
    profile_api.assert_awaited_once()
    find_api.assert_awaited_once()
    assert "profile" not in metadata["authors"][0]


def test_preload_limits_concurrent_lookups_and_caches_unavailable_profiles():
    active = 0
    maximum = 0

    async def profile(*_args):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"available": False}

    ns = _preload_namespace(profile, AsyncMock(return_value={"available": False}))
    metadata = {
        "title": TITLE,
        "authors": [{"name": str(i), "openalex_id": f"A{i}"} for i in range(10)],
    }
    result = asyncio.run(ns["_preload_paper_author_profiles"](metadata, object()))
    assert maximum == 3
    assert len(result["authors"]) == 10
    assert all(a["profile"] == {"available": False} for a in result["authors"])
    assert all(a["profile_lookup_complete"] for a in result["authors"])
    assert ns["logger"].info.call_count == 10


def test_endpoint_uses_original_title_and_persists(monkeypatch):
    ns = _endpoint_namespace({
        "paper_title": TITLE, "custom_label": "Do not search this",
        "paper_source": "https://arxiv.org/abs/2501.12345", "source_type": "url",
    })
    metadata = {"available": True, "authors": [{"name": "Jane Doe"}]}
    resolver = MagicMock(return_value=metadata)
    monkeypatch.setattr(paper_metadata, "resolve_paper_authors", resolver)
    assert asyncio.run(ns["paper_authors"](42, object())) == metadata
    resolver.assert_called_once_with(
        TITLE, doi=None, arxiv_id="2501.12345", cache_dir="cache",
        semantic_scholar_api_key=None,
    )
    ns["db"].update_check_paper_metadata.assert_awaited_once_with(42, metadata)


def test_endpoint_enforces_ownership_before_lookup(monkeypatch):
    ns = _endpoint_namespace({})
    ns["_get_owned_check_or_404"].side_effect = HTTPException(status_code=404)
    resolver = MagicMock()
    monkeypatch.setattr(paper_metadata, "resolve_paper_authors", resolver)
    with pytest.raises(HTTPException) as error:
        asyncio.run(ns["paper_authors"](42, object()))
    assert error.value.status_code == 404
    resolver.assert_not_called()


def test_endpoint_surfaces_lookup_failure(monkeypatch):
    ns = _endpoint_namespace({"paper_title": TITLE})
    monkeypatch.setattr(paper_metadata, "resolve_paper_authors", MagicMock(side_effect=RuntimeError("offline")))
    with pytest.raises(HTTPException) as error:
        asyncio.run(ns["paper_authors"](42, object()))
    assert error.value.status_code == 502
    ns["logger"].error.assert_called_once()
