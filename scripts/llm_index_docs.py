"""
LLM-Powered Documentation Indexing Script
=========================================

This script uses a local OpenAI-compatible LLM server (e.g., LM Studio) to generate a mapping between project documentation files and the project specification. It produces a Markdown index (`docs_index.md`) that shows how each documentation file relates to the project requirements and highlights any gaps or missing links.

Key Features:

- Automated doc indexing using an LLM
- Local LLM server support (default: http://127.0.0.1:1234/v1)
- Prompt size management to fit model context window
- PR-ready Markdown output for documentation review

Usage:

1. Start your local LLM server (e.g., LM Studio with a supported model)
2. Set a dummy API key if required: $env:OPENAI_API_KEY="sk-local"
3. Run: python scripts/llm_index_docs.py
4. Review the generated docs_index.md

Example output: A table mapping each doc to relevant spec sections, with notes on coverage and gaps.

See the PR or README for more details.
"""

import os
import openai  # You can swap for anthropic, etc.
from pathlib import Path

def collect_markdown_docs(root="."):
    docs = {}
    for path in Path(root).rglob("*.md"):
        # Skip virtualenvs, build, etc.
        if any(part in {".venv", "venv", "build", "dist", ".git"} for part in path.parts):
            continue
        with open(path, encoding="utf-8") as f:
            docs[str(path)] = f.read()
    return docs

def get_specification_text():
    # Concatenate README and copilot-instructions as the spec
    spec_files = ["README.md", ".github/copilot-instructions.md"]
    spec = ""
    for fname in spec_files:
        if os.path.exists(fname):
            with open(fname, encoding="utf-8") as f:
                spec += f"\n---\n{fname}:\n" + f.read()
    return spec

def ask_llm_to_index(docs, spec, api_key):
    openai.api_key = api_key
    # Support both openai-python v1.x (base_url) and v0.x (api_base)
    try:
        openai.base_url = "http://127.0.0.1:1234/v1"
    except AttributeError:
        openai.api_base = "http://127.0.0.1:1234/v1"
    print("[DEBUG] Sending request to local LLM server at http://127.0.0.1:1234/v1 ...")
    # Limit number of files and characters per file to avoid context overflow
    MAX_FILES = 5
    MAX_CHARS_PER_FILE = 1000
    selected_docs = list(docs.items())[:MAX_FILES]
    prompt = (
        "Given the following project specification:\n"
        f"{spec[:3000]}\n\n"  # Truncate spec if needed
        "And the following documentation files:\n"
        + "\n\n".join([f"---\n{path}:\n{content[:MAX_CHARS_PER_FILE]}" for path, content in selected_docs])
        + "\n\nFor each documentation file, explain how it relates to the project specification, "
        + "what requirements it covers, and whether there are any gaps or missing links. "
        + "Produce a table or index mapping each doc to the relevant spec sections."
    )
    client = openai.OpenAI(api_key=api_key, base_url="http://127.0.0.1:1234/v1")
    print("[DEBUG] Streaming response from LLM server...")
    stream = client.chat.completions.create(
        model="gpt-4o",  # or your preferred model
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
        stream=True
    )
    full_content = ""
    for chunk in stream:
        delta = getattr(chunk.choices[0].delta, "content", None)
        if delta:
            print(delta, end="", flush=True)
            full_content += delta
    print()  # Newline after streaming output
    return full_content

if __name__ == "__main__":
    docs = collect_markdown_docs()
    spec = get_specification_text()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Please set the OPENAI_API_KEY environment variable.")
        exit(1)
    index = ask_llm_to_index(docs, spec, api_key)
    with open("docs_index.md", "w", encoding="utf-8") as f:
        f.write(index)
    print("LLM documentation index written to docs_index.md")
