"""Verify default Google model selection uses the supported stable ID."""

from refchecker.config.settings import (
    DEFAULT_EXTRACTION_MODELS,
    DEFAULT_HALLUCINATION_MODELS,
    DEFAULT_WEB_SEARCH_MODELS,
)


def test_google_default_routes_agree():
    """Bulk, CLI, and WebUI share one model for Google's checker paths."""
    assert DEFAULT_EXTRACTION_MODELS["google"] == "gemini-3.1-flash-lite"
    assert DEFAULT_HALLUCINATION_MODELS["google"] == DEFAULT_EXTRACTION_MODELS["google"]
    assert DEFAULT_WEB_SEARCH_MODELS["google"] == DEFAULT_EXTRACTION_MODELS["google"]
