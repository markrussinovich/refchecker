# Copilot Instructions for RefChecker

## Project Overview
- **Purpose:** RefChecker validates the accuracy of academic paper references by comparing extracted citations against authoritative sources (Semantic Scholar, OpenAlex, CrossRef).
- **Input Types:** Supports ArXiv IDs/URLs, local PDFs, LaTeX, and plain text files.
- **LLM Integration:** Reference extraction can be enhanced with LLMs (OpenAI, Anthropic, Google, Azure, vLLM). LLM provider and model are configurable via CLI or environment variables.
- **Local DB:** Optionally uses a local Semantic Scholar database for faster, offline verification.

## Architecture & Key Components
- **Entry Point:** `refchecker.py` (CLI, main logic)
- **Core Logic:** `src/core/refchecker.py` (reference checking pipeline)
- **Checkers:** `src/checkers/` (modular source checkers: crossref, openalex, semantic_scholar, etc.)
- **LLM Providers:** `src/llm/providers.py` (LLM API integration)
- **Database:** `src/database/` (local Semantic Scholar DB download/utilities)
- **Utilities:** `src/utils/` (text, DOI, author, config, error handling)
- **PDF/LaTeX/Text Processing:** `src/services/pdf_processor.py`, `src/utils/text_utils.py`
- **Configuration:** `src/config/settings.py`, `src/config/logging.conf`

## Developer Workflows
- **Install (dev + LLM support):**
  ```bash
  pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ refchecker[llm,dev,optional]
  ```
- **Run CLI:**
  ```bash
  python refchecker.py --paper 1706.03762 [--llm-provider openai --llm-model gpt-4o]
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

## Project Conventions & Patterns
- **All reference checking logic is modularized in `src/checkers/` and orchestrated by `src/core/refchecker.py`**
- **LLM provider/model selection is handled via CLI args or environment variables.**
- **API keys are loaded from environment variables or prompted interactively.**
- **Error/warning types are standardized (author, title, year, venue, url, doi, unverified).**
- **Test suite is organized by type: `tests/unit/`, `tests/integration/`, `tests/e2e/`.**
- **Version is managed in `src/__version__.py` and updated before builds.**

## Integration Points
- **External APIs:** Semantic Scholar, OpenAlex, CrossRef, LLM providers (OpenAI, Anthropic, Google, Azure, vLLM)
- **Local DB:** Used for offline/fast lookups (see `src/database/` and `download_semantic_scholar_db.py`)
- **LLM:** Used for reference extraction/parsing (see `src/llm/`)

## Examples
- **Check a paper with LLM extraction:**
  ```bash
  python refchecker.py --paper 1706.03762 --llm-provider openai --llm-model gpt-4o
  ```
- **Check a local PDF with local DB:**
  ```bash
  python refchecker.py --paper /path/to/paper.pdf --db-path semantic_scholar_db/semantic_scholar.db
  ```

## See Also
- [README.md](../README.md) for full usage, configuration, and troubleshooting details.
- [tests/README.md](../tests/README.md) for test documentation.
