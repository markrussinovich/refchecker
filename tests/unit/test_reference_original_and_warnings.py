import asyncio
from unittest.mock import AsyncMock

from backend.database import db
from backend.refchecker_wrapper import ProgressRefChecker


def checker():
    instance = ProgressRefChecker.__new__(ProgressRefChecker)
    instance.emit_progress = AsyncMock()
    instance._check_cancelled = AsyncMock()
    return instance


def test_error_result_preserves_extracted_reference():
    reference = {"title": "A paper", "authors": ["Wrong Author"], "raw_text": "Original citation"}
    result = checker()._format_error_result(reference, 1, RuntimeError("failed"))
    assert result["original_reference"] == reference
    assert result["original_reference"] is not reference


def test_cache_hit_uses_this_papers_original_not_previous_citation(monkeypatch):
    monkeypatch.setattr(db, "lookup_verified_reference", AsyncMock(return_value={
        "result": {
            "title": "A paper", "authors": ["Verified Author"],
            "original_reference": {"raw_text": "Previous paper's citation"},
        },
    }))
    reference = {"title": "A paper", "raw_text": "Current paper's citation"}

    async def run():
        return await checker()._check_single_reference_with_limit(
            reference, 0, 1, asyncio.get_running_loop(), asyncio.Semaphore(1),
        )

    result = asyncio.run(run())
    assert result["original_reference"] == reference
    assert result["authors"] == ["Verified Author"]


def test_cross_check_retains_distinct_prior_venues_in_one_warning(monkeypatch):
    monkeypatch.setattr(db, "lookup_verified_reference", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "find_verified_by_fuzzy", AsyncMock(return_value=None))
    entries = [{
        "cached_title": "A paper", "cached_identity": str(i),
        "diffs": [{"field": "venue", "cited": "arXiv", "cached": venue}],
    } for i, venue in enumerate(["CAMLIS", "CAMLIS 2024, pages 48-62", "CAMLIS"])]
    monkeypatch.setattr(db, "cross_check_seen_refs", AsyncMock(return_value=entries))
    instance = checker()
    instance._check_reference_sync = lambda *_args: {"status": "verified", "warnings": []}
    reference = {"title": "A paper", "venue": "arXiv"}

    async def run():
        return await instance._check_single_reference_with_limit(
            reference, 0, 1, asyncio.get_running_loop(), asyncio.Semaphore(1),
        )

    result = asyncio.run(run())
    assert len(result["warnings"]) == 1
    warning = result["warnings"][0]
    assert len(warning["diffs"]) == 2
    assert warning["cached_matches"] == entries
    assert "previously: CAMLIS;" in warning["warning_details"]
    assert "previously: CAMLIS 2024, pages 48-62" in warning["warning_details"]
    assert result["original_reference"] == reference
