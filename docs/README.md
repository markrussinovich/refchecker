# RefChecker Docs

Canonical project documentation lives in this directory.

## Guides

- [Web UI Guide](web-ui.md) — setup, runtime modes, API-backed and local database configuration, API surface, and troubleshooting
- [Testing Guide](testing.md) — suite structure, recommended pytest commands, markers, and debugging workflow

## Extraction Modes

- LLM extraction is generally the most accurate option for complex bibliographies and PDFs.
- When no extraction LLM is configured, PDF extraction can fall back to GROBID.
- Hallucination checks use a separate hallucination-capable LLM selection when configured, and require OpenAI, Anthropic, Google, or Azure for live web search.
- Deep hallucination checks can re-verify a reference against LLM-found title, authors, year, and link when the LLM finds a more likely match than the first database result.

The top-level [README.md](../README.md) stays focused on installation, quick start, and core capabilities. Use the guides in this folder for operational detail.
