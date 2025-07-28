# Copilot Instructions for RefChecker

## Project Architecture & Key Concepts

- **Purpose:** RefChecker validates academic paper references by extracting citations from ArXiv, PDF, LaTeX, or text, and verifying them against authoritative sources (Semantic Scholar, OpenAlex, CrossRef). LLMs can be used for advanced reference extraction.
- **Entry Point:** `refchecker.py` (CLI, main logic)
- **Core Pipeline:** `src/core/refchecker.py` orchestrates the reference checking workflow.
- **Checkers:** Modular source checkers in `src/checkers/` (e.g., `crossref.py`, `openalex.py`, `semantic_scholar.py`, `github_checker.py`). Each checker encapsulates API logic for a specific source.
- **LLM Integration:** `src/llm/providers.py` implements provider classes for OpenAI, Anthropic, Google, Azure, and vLLM. LLM provider/model is selected via CLI or environment variables. API keys are loaded from env or prompted interactively.
- **Local DB:** `src/database/` and `download_semantic_scholar_db.py` support offline/fast lookups using a local Semantic Scholar SQLite DB.
- **Utilities:** `src/utils/` (text, DOI, author, config, error handling), `src/services/pdf_processor.py` (PDF/LaTeX parsing).
- **Configuration:** `src/config/settings.py` (runtime config), `src/config/logging.conf` (logging).
- **Versioning:** `src/__version__.py` is the single source of truth for the package version.

## Developer Workflows

- **Install (dev + LLM support):**
  ```bash
  pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ refchecker[llm,dev,optional]
  ```
- **Run CLI:**
  ```bash
  python refchecker.py --paper 1706.03762 --llm-provider openai --llm-model gpt-4o
  ```
- **Run Tests:**
  ```bash
  pytest tests/
  pytest tests/unit/           # Unit tests
  pytest tests/integration/    # Integration tests
  pytest tests/e2e/            # End-to-end tests
  pytest --cov=src --cov-report=html tests/
  pytest -n auto tests/        # Parallel (if pytest-xdist)
  ```
- **Build Package:**
  ```bash
  ./build.sh
  ```
- **Download Local DB:**
  ```bash
  python download_semantic_scholar_db.py --field "computer science" --start-year 2020 --end-year 2024
  ```
- **Generate LLM Doc Index:**
  ```bash
  python scripts/llm_index_docs.py
  # Output: docs_index.md
  ```

## Project Conventions & Patterns

- All reference checking logic is modularized in `src/checkers/` and orchestrated by `src/core/refchecker.py`.
- LLM provider/model selection is handled via CLI args or environment variables. API keys are loaded from env or prompted interactively (see README for details).
- Error/warning types are standardized: `author`, `title`, `year`, `venue`, `url`, `doi`, `unverified`.
- Test suite is organized by type: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Test data/mocks in `tests/fixtures/`.
- All external API calls are mocked in tests; use `disable_network_calls` fixture to prevent real network access.
- Version is managed in `src/__version__.py` and must be updated before builds.

## Integration Points

- **External APIs:** Semantic Scholar, OpenAlex, CrossRef, LLM providers (OpenAI, Anthropic, Google, Azure, vLLM), GitHub.
- **Local DB:** Used for offline/fast lookups (see `src/database/` and `download_semantic_scholar_db.py`).
- **LLM:** Used for reference extraction/parsing (see `src/llm/`).
- **Docker:** Dockerfile provided for reproducible dev environments. Mount workspace to persist outputs.

## Examples

- **Check a paper with LLM extraction:**
  ```bash
  python refchecker.py --paper 1706.03762 --llm-provider openai --llm-model gpt-4o
  ```
- **Check a local PDF with local DB:**
  ```bash
  python refchecker.py --paper /path/to/paper.pdf --db-path semantic_scholar_db/semantic_scholar.db
  ```
- **Generate documentation/spec index with LLM:**
  ```bash
  python scripts/llm_index_docs.py
  # Output: docs_index.md
  ```

## See Also
- [README.md](../README.md) for full usage, configuration, and troubleshooting details.
- [tests/README.md](../tests/README.md) for test documentation and patterns.
