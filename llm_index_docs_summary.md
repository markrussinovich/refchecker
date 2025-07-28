# LLM-Powered Documentation Indexing Script

This script ([scripts/llm_index_docs.py](scripts/llm_index_docs.py)) uses a local OpenAI-compatible LLM server (e.g., LM Studio) to generate a mapping between project documentation files and the project specification. It produces a Markdown index ([docs_index.md](docs_index.md)) that shows how each documentation file relates to the project requirements and highlights any gaps or missing links.

## Key Features
- Automated doc indexing using an LLM
- Local LLM server support (default: `http://127.0.0.1:1234/v1`)
- Prompt size management to fit model context window
- PR-ready Markdown output for documentation review

## Usage
1. Start your local LLM server (e.g., LM Studio with a supported model)
2. Set a dummy API key if required:
   ```pwsh
   $env:OPENAI_API_KEY="sk-local"
   ```
3. Run:
   ```pwsh
   python scripts/llm_index_docs.py
   ```
4. Review the generated [docs_index.md](docs_index.md)

## Example Output
A table mapping each doc to relevant spec sections, with notes on coverage and gaps.

## Implementation Notes
- Compatible with OpenAI Python client v1.x+
- Prompt size is limited by `MAX_FILES` and `MAX_CHARS_PER_FILE` to avoid context overflow
- Can be further customized to include/exclude specific files or sections

See the [PR_llm_index_docs.md](PR_llm_index_docs.md) or [README.md](README.md) for more details.
