# RefChecker Docs

Canonical project documentation lives in this directory.

## Guides

- [Web UI Guide](web-ui.md) — setup, runtime modes, API-backed and local database configuration, API surface, and troubleshooting
- [Testing Guide](testing.md) — suite structure, recommended pytest commands, markers, and debugging workflow

## Extraction Modes

- LLM extraction is generally the most accurate option for complex bibliographies and PDFs.
- When no LLM is configured, PDF extraction can fall back to GROBID.
- Hallucination web-search checks require an LLM provider.

The top-level [README.md](../README.md) stays focused on installation, quick start, and core capabilities. Use the guides in this folder for operational detail.