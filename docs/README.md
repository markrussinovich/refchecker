# RefChecker Docs

Canonical project documentation lives in this directory.

## Guides

- [Feature Guide & Access-Method Matrix](FEATURES.md) — per-feature guides across web / desktop / CLI / API, with CLI usage examples that match `refchecker-webui check --help`
- [Multi-User & Teams Setup](MULTIUSER.md) — enable accounts, Teams, and presence from the in-app form (hot-reload) or via environment variables
- [Web UI Guide](web-ui.md) — setup, runtime modes, API-backed and local database configuration, API surface, the `refchecker-webui check` single-paper CLI, and troubleshooting
- [Testing Guide](testing.md) — suite structure, recommended pytest commands, markers, and debugging workflow

## Access methods

RefChecker exposes one verification engine through the Web UI, the desktop (Tauri) app, the CLI, and the HTTP API. The top-level [README feature matrix](../README.md#feature-matrix-web--desktop--cli--api) (and the fuller [docs/FEATURES.md](FEATURES.md)) show where each capability (hallucination check, inline-citation/ordering, retraction screening, gap-finder, enrichment, opt-in AI detection, and the web/desktop-only interactive surfaces) is available, and the [CLI guide](../README.md#cli) documents the `refchecker-webui check` flags (which match `refchecker-webui check --help`).

## Extraction Modes

- LLM extraction is generally the most accurate option for complex bibliographies and PDFs.
- When no extraction LLM is configured, PDF extraction can fall back to GROBID.
- Hallucination checks use a separate hallucination-capable LLM selection when configured, and require OpenAI, Anthropic, Google, or Azure for live web search.
- Deep hallucination checks can re-verify a reference against LLM-found title, authors, year, and link when the LLM finds a more likely match than the first database result.

The top-level [README.md](../README.md) stays focused on installation, quick start, and core capabilities. Use the guides in this folder for operational detail.
