"""Regression tests for backend settings and configuration.

These tests ensure that critical settings and fallback behaviors
are not accidentally removed during cleanup commits.
"""
import os
import re
import ast
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Helpers — parse the backend source to verify structural invariants without
# importing (and thus starting) the FastAPI app.
# ---------------------------------------------------------------------------

_BACKEND_MAIN = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, "backend", "main.py"
)


def _read_backend_main() -> str:
    with open(_BACKEND_MAIN, encoding="utf-8") as f:
        return f.read()


_REFCHECKER_WRAPPER = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, "backend", "refchecker_wrapper.py"
)


def _read_refchecker_wrapper() -> str:
    with open(_REFCHECKER_WRAPPER, encoding="utf-8") as f:
        return f.read()


def _get_progress_refchecker_check_paper() -> ast.AsyncFunctionDef:
    tree = ast.parse(_read_refchecker_wrapper())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ProgressRefChecker":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "check_paper":
                    return item
    raise AssertionError("ProgressRefChecker.check_paper not found in backend/refchecker_wrapper.py")


# ---------------------------------------------------------------------------
# 1. db_path must be in the settings config
# ---------------------------------------------------------------------------

class TestDbPathSetting:
    """The local Semantic Scholar DB path must be configurable from the UI."""

    def test_settings_config_contains_db_path(self):
        """GET /api/settings must include db_path in settings_config."""
        src = _read_backend_main()
        assert '"db_path"' in src, (
            "db_path is missing from GET /api/settings — "
            "users cannot configure the local Semantic Scholar database"
        )

    def test_db_path_in_valid_keys(self):
        """PUT /api/settings/{key} must accept db_path."""
        src = _read_backend_main()
        # Find the valid_keys set definition
        match = re.search(r'valid_keys\s*=\s*\{([^}]+)\}', src)
        assert match, "valid_keys set not found in backend/main.py"
        assert "db_path" in match.group(1), (
            "db_path is not in valid_keys — "
            "the PUT /api/settings/db_path endpoint will reject it"
        )

    def test_run_check_resolves_db_path_from_settings(self):
        """run_check must fall back to db.get_setting('db_path')."""
        src = _read_backend_main()
        assert 'get_setting("db_path")' in src or "get_setting('db_path')" in src, (
            "run_check does not fall back to db_path from settings — "
            "the UI-configured path will be ignored"
        )

    def test_backend_supports_database_directory_env_var(self):
        """Web UI should discover DBs from REFCHECKER_DATABASE_DIRECTORY."""
        src = _read_backend_main()
        assert "REFCHECKER_DATABASE_DIRECTORY" in src, (
            "backend/main.py does not reference REFCHECKER_DATABASE_DIRECTORY — "
            "web UI cannot discover multiple local DBs by filename"
        )


# ---------------------------------------------------------------------------
# 2. Thumbnail fallback for ArXiv papers
# ---------------------------------------------------------------------------

class TestThumbnailFallback:
    """ArXiv thumbnail generation must fall back to text placeholder."""

    def test_arxiv_thumbnail_has_fallback(self):
        """After generate_arxiv_thumbnail_async, there must be a fallback."""
        src = _read_backend_main()
        # Find the arxiv thumbnail block — expect a fallback within ~5 lines
        pattern = r'generate_arxiv_thumbnail_async\(arxiv_id, check_id(?:,\s*cache_dir=cache_dir)?\).*?(?:get_text_thumbnail_async|generate_pdf_thumbnail)'
        match = re.search(pattern, src, re.DOTALL)
        assert match, (
            "No text-thumbnail fallback after generate_arxiv_thumbnail_async — "
            "ArXiv papers that fail thumbnail generation will show broken images"
        )


# ---------------------------------------------------------------------------
# 3. Cache helper scoping in the wrapper
# ---------------------------------------------------------------------------

class TestCacheHelperScoping:
    """Cache helpers must not be locally imported inside check_paper branches."""

    def test_check_paper_does_not_shadow_cache_helpers(self):
        """Local cache helper imports cause branch-specific UnboundLocalError."""
        check_paper = _get_progress_refchecker_check_paper()
        helper_names = {"cache_bibliography", "cached_bibliography", "get_cached_artifact_path"}
        local_import_lines = [
            node.lineno
            for node in ast.walk(check_paper)
            if isinstance(node, ast.ImportFrom)
            and node.module == "refchecker.utils.cache_utils"
            and any(alias.name in helper_names for alias in node.names)
        ]

        assert not local_import_lines, (
            "ProgressRefChecker.check_paper locally imports cache helpers, "
            "which shadows later branches and can raise UnboundLocalError. "
            f"Offending lines: {local_import_lines}"
        )


# ---------------------------------------------------------------------------
# 4. Zero-byte PDF cache protection
# ---------------------------------------------------------------------------

class TestPdfCacheSizeCheck:
    """Cached PDFs must be re-downloaded if they are zero-byte (corrupt)."""

    def test_thumbnail_endpoint_checks_pdf_size(self):
        """The thumbnail endpoint must check for zero-byte cached PDFs."""
        src = _read_backend_main()
        # Look for getsize or st_size check near the thumbnail PDF cache
        thumbnail_section = src[src.find("def get_thumbnail"):src.find("def get_preview")]
        assert "getsize" in thumbnail_section or "st_size" in thumbnail_section, (
            "Thumbnail endpoint does not check for zero-byte cached PDFs — "
            "corrupt empty files will be served instead of re-downloaded"
        )

    def test_preview_endpoint_checks_pdf_size(self):
        """The preview endpoint must check for zero-byte cached PDFs."""
        src = _read_backend_main()
        preview_section = src[src.find("def get_preview"):]
        # Truncate to just the function
        next_def = preview_section.find("\nasync def ", 10)
        if next_def > 0:
            preview_section = preview_section[:next_def]
        assert "getsize" in preview_section or "st_size" in preview_section, (
            "Preview endpoint does not check for zero-byte cached PDFs — "
            "corrupt empty files will be served instead of re-downloaded"
        )


# ---------------------------------------------------------------------------
# 5. DOI validation in bulk pipeline
# ---------------------------------------------------------------------------

class TestBulkPipelineDOIValidation:
    """DOI strings must be validated before sending to Semantic Scholar."""

    def test_extract_ss_id_validates_doi_format(self):
        """_extract_ss_id must call is_valid_doi_format, not just startswith('10.')."""
        from refchecker.core.bulk_pipeline import _extract_ss_id

        # A valid-looking DOI prefix but malformed overall
        ref_bad = {"doi": "10."}
        result = _extract_ss_id(ref_bad)
        assert result is None, (
            "_extract_ss_id accepted a malformed DOI '10.' — "
            "is_valid_doi_format check may be missing"
        )

    def test_extract_ss_id_accepts_valid_doi(self):
        from refchecker.core.bulk_pipeline import _extract_ss_id

        ref = {"doi": "10.1234/test.2024"}
        result = _extract_ss_id(ref)
        assert result == "DOI:10.1234/test.2024"

    def test_extract_ss_id_rejects_truncated_doi(self):
        from refchecker.core.bulk_pipeline import _extract_ss_id

        ref = {"doi": "10.1234"}
        result = _extract_ss_id(ref)
        assert result is None, (
            "_extract_ss_id accepted truncated DOI '10.1234' without suffix"
        )


# ---------------------------------------------------------------------------
# 6. Semantic Scholar URL construction in bulk pipeline
# ---------------------------------------------------------------------------

class TestSemanticScholarURLConstruction:
    """Semantic Scholar URLs must use the correct format for numeric IDs."""

    def test_bulk_pipeline_uses_construct_function(self):
        """Bulk pipeline should use construct_semantic_scholar_url, not hardcoded URLs."""
        bulk_path = os.path.join(
            os.path.dirname(__file__), os.pardir, os.pardir,
            "src", "refchecker", "core", "bulk_pipeline.py",
        )
        with open(bulk_path, encoding="utf-8") as f:
            src = f.read()
        # Find the batch prefetch section
        prefetch_section = src[src.find("def _batch_prefetch_ss_metadata"):]
        assert "construct_semantic_scholar_url" in prefetch_section, (
            "Bulk pipeline inlines Semantic Scholar URL construction instead of "
            "using construct_semantic_scholar_url — numeric CorpusIds will get "
            "wrong URLs"
        )

    def test_construct_semantic_scholar_url_handles_numeric_id(self):
        """Numeric paper IDs should use the CorpusID API URL."""
        from refchecker.utils.url_utils import construct_semantic_scholar_url

        url = construct_semantic_scholar_url("270688189")
        assert "CorpusID:270688189" in url, (
            "construct_semantic_scholar_url does not handle numeric CorpusIds"
        )

    def test_construct_semantic_scholar_url_handles_hash_id(self):
        """Hash paper IDs should use the /paper/ web URL."""
        from refchecker.utils.url_utils import construct_semantic_scholar_url

        url = construct_semantic_scholar_url("abc123def456")
        assert "/paper/abc123def456" in url
