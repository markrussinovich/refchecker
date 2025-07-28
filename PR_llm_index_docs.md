# PR: Add LLM-Powered Documentation Indexing Script

## Overview

This PR introduces a new script, `llm_index_docs.py`, which leverages a local OpenAI-compatible LLM server (e.g., LM Studio) to automatically generate a mapping between project documentation files and the project specification. The script produces a Markdown index (`docs_index.md`) that highlights how each documentation file relates to the project requirements, and identifies any gaps or missing links.

## Key Features

- **Automated Doc Indexing:** Uses an LLM to analyze all Markdown documentation in the repo and relate them to the project spec.
- **Local LLM Support:** Connects to a local OpenAI-compatible server (default: `http://127.0.0.1:1234/v1`), supporting models like `microsoft/phi-4`.
- **Prompt Size Management:** Automatically truncates the prompt to fit within the model’s context window, avoiding server errors.
- **PR-Ready Output:** Generates a Markdown table mapping each doc to relevant spec sections, with notes on coverage and gaps.

## Usage

1. **Start your local LLM server** (e.g., LM Studio with a supported model).
2. **Set a dummy API key** (if required by your client library):
   ```pwsh
   $env:OPENAI_API_KEY="sk-local"
   ```
3. **Run the script:**
   ```pwsh
   python scripts/llm_index_docs.py
   ```
4. **Review the generated `docs_index.md`** for a summary of documentation coverage and gaps.

## Example Output

| Documentation File             | Relevant Specification Sections Covered                                                                 | Notes (Gaps/Missing Links)                                                                 |
|-------------------------------|--------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| README.md                      | - 📊 Sample Output<br>- 🎯 Features<br>- 🗄️ Local Database Setup | - Provides a high-level overview of features and sample output.<br> - No explicit mention of usage instructions or specific installation steps. |
| copilot-instructions.md | - 🤖 LLM-Enhanced Reference Extraction<br>- ⚙️ Configuration | - Offers detailed insights into project architecture and LLM integration, but lacks explicit configuration examples. |
| README.md                 | - 🧪 Testing<br>- e2e/                         | - Describes the test suite structure comprehensively.<br> - No direct mention of how testing ties into the project's continuous integration.    |

## Implementation Notes

- The script is compatible with OpenAI Python client v1.x+.
- Prompt size is limited by `MAX_FILES` and `MAX_CHARS_PER_FILE` to avoid context overflow.
- The script can be further customized to include/exclude specific files or sections.

## Next Steps

- Integrate this script into CI for automated doc coverage checks.
- Tune prompt size and file selection for larger projects or different models.
- Optionally, extend to support remote LLM APIs or additional output formats.
