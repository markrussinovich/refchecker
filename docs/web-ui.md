# RefChecker Web UI

This guide is the canonical reference for the Web UI.

## Overview

The Web UI provides a real-time interface for checking references in single papers and batches. It includes history, exports, per-reference diagnostics, split LLM configuration for extraction and hallucination checks, and hosted multi-user support.

## Extraction Behavior

- If an extraction LLM provider is configured, RefChecker uses it for higher-quality extraction from PDFs and unusual bibliography formats.
- If no extraction LLM is configured, PDF extraction can fall back to GROBID.
- Hallucination checks use a separate hallucination LLM selection when one is configured. The hallucination provider must be web-search capable: OpenAI, Anthropic, Google, or Azure.
- Local vLLM can be selected for extraction, but it is not offered for hallucination checks because local models cannot perform live web search.

GROBID details:

- default endpoint: `http://localhost:8070`
- override with `GROBID_URL`
- when Docker is available, RefChecker can auto-start `lfoppiano/grobid:0.8.2`

## Quick Start

### Option 1: Installed Package

```bash
pip install academic-refchecker[webui]
refchecker-webui
```

Open `http://localhost:8000` in your browser.

Recommended when you also want LLM extraction and hallucination checks:

```bash
pip install academic-refchecker[llm,webui]
```

Useful flags:

```bash
refchecker-webui --port 8080
refchecker-webui --host 0.0.0.0
refchecker-webui --database-dir /path/to/local-db-folder
```

### Option 2: Development Mode

Prerequisites:

- Python 3.11+
- Node.js 20.19+
- npm

```bash
pip install -e ".[llm,webui]"
cd web-ui
npm install
npm start
```

This starts the backend on `http://localhost:8000` and the Vite frontend on `http://localhost:5173`.

To run the servers separately:

```bash
# Terminal 1
python -m uvicorn backend.main:app --reload --port 8000

# Terminal 2
cd web-ui
npm run dev
```

## Features

- Real-time progress updates over WebSockets
- ArXiv IDs/URLs, file uploads, and bulk ZIP or multi-file workflows
- History sidebar with re-run and deletion controls
- Export as Markdown, plain text, or BibTeX
- Per-reference links to Semantic Scholar, DOI, and ArXiv
- API-backed verification via Semantic Scholar, OpenAlex, CrossRef, DBLP, and ACL Anthology
- Optional local/offline databases via `semantic_scholar.db`, `openalex.db`, `crossref.db`, `dblp.db`, and `acl_anthology.db`
- Theme support and hosted multi-user mode
- Separate extraction and hallucination LLM selectors with per-config API keys

## Input Modes

### Single Paper

- enter an ArXiv ID or URL
- upload a PDF, LaTeX source, plain text file, or bibliography file

### Bulk Checking

- upload multiple files at once
- upload a ZIP containing supported paper files
- assign an optional batch label for history organization

## Verification Sources

API-backed lookups:

- Semantic Scholar API
- OpenAlex API
- CrossRef API
- DBLP API
- ACL Anthology API

Local/offline databases:

- `semantic_scholar.db`
- `openalex.db`
- `crossref.db`
- `dblp.db`
- `acl_anthology.db`

When a local database is present, the Web UI uses it first and falls back to the corresponding APIs when necessary.

## Configuration

### Environment Variables

LLM providers are optional for extraction but required for deep hallucination checks. The UI stores an extraction selection and a hallucination selection separately in the browser. Extraction may use OpenAI, Anthropic, Google, Azure, or vLLM. Hallucination checks only use OpenAI, Anthropic, Google, or Azure.

```bash
export ANTHROPIC_API_KEY=your_key_here
# or
export OPENAI_API_KEY=your_key_here
# or
export GOOGLE_API_KEY=your_key_here
```

Saved LLM configurations include provider, model, optional endpoint, and API key state. In single-user mode, API keys may be stored server-side in the local SQLite settings database. In multi-user mode, user-entered keys stay in the browser and are sent with each request; the server stores per-user configuration metadata but not browser-only keys.

For a run, the Web UI sends both:

- `llm_config_id` / `llm_provider` / `llm_model` for extraction
- `hallucination_config_id` / `hallucination_provider` / `hallucination_model` for hallucination checks

If no separate hallucination selection is available, the UI falls back to the selected extraction configuration only when that provider is hallucination-capable.

Optional configuration:

```bash
export GROBID_URL=http://localhost:8070
```

The Semantic Scholar API key is entered in the UI settings panel. In multi-user mode it is kept in the encrypted browser key cache when browser crypto APIs are available and is not stored on the server. In single-user mode it is stored encrypted in the local RefChecker database.

### Local Database Directory

Single-user mode exposes a `Local Database Directory` field in Settings. Point it at a folder containing any combination of:

- `semantic_scholar.db`
- `openalex.db`
- `crossref.db`
- `dblp.db`
- `acl_anthology.db`

You can also configure the same directory when starting the server:

```bash
refchecker-webui --database-dir /path/to/local-db-folder
```

The setting accepts a directory and still tolerates a direct `semantic_scholar.db` path for backward compatibility, but the directory form is what enables multi-database discovery.

Build or refresh local databases with the CLI updater:

```bash
academic-refchecker --database-dir /path/to/local-db-folder --update-databases
academic-refchecker --database-dir /path/to/local-db-folder --update-databases --openalex-min-year 2020
```

The Web UI refreshes databases it already finds in that directory on startup. The CLI updater remains the canonical way to do the initial population of a new local database directory.

## API Surface

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/check` | Start a new check from upload or URL |
| GET | `/api/history` | List prior checks |
| GET | `/api/history/{id}` | Fetch one check result |
| POST | `/api/recheck/{id}` | Re-run a saved check |
| DELETE | `/api/history/{id}` | Delete a saved check |
| PUT | `/api/history/{id}` | Update stored metadata such as title |
| GET | `/api/llm-configs` | List saved LLM configurations |
| POST | `/api/llm-configs` | Create a saved LLM configuration |
| PUT | `/api/llm-configs/{config_id}` | Update a saved LLM configuration |
| DELETE | `/api/llm-configs/{config_id}` | Delete a saved LLM configuration |
| POST | `/api/llm-configs/{config_id}/set-default` | Set the default extraction LLM configuration |
| POST | `/api/llm-configs/validate` | Validate an LLM provider/model/key combination |

### WebSocket

Connect to `WS /api/ws/{session_id}` for live progress.

Common message types:

- `started`
- `extracting`
- `progress`
- `reference_result`
- `summary_update`
- `completed`
- `error`

## Hallucination Check Flow

After normal database verification, suspicious references are sent through the deep hallucination checker. The checker first applies deterministic filters so year-only and minor venue differences do not trigger unnecessary LLM work. Suspicious cases include unverified references, low author overlap, identifier conflicts, and URLs that resolve to another work.

The hallucination LLM must perform a web search and return a structured result with a verdict, explanation, link, found title, found authors, and found year. If it finds a dedicated page for the cited work and returns `UNLIKELY`, RefChecker re-runs its standard title, author, and year comparisons against that LLM-found metadata. This reverification can clear stale unverified errors or wrong database-match errors when the LLM found the citation's actual source. If the recheck still finds substantive mismatches, the reference remains an error. If no exact source is found, or the source conflicts with the cited title/authors/identifier, the reference can be marked as a likely hallucination.

The Web UI shows these results on the reference card, adds any LLM-found source as an `llm_verified` URL, and includes the hallucination provider/model in check history.

## Frontend Layout

```text
web-ui/
├── src/
│   ├── components/
│   ├── stores/
│   ├── utils/
│   └── App.jsx
├── e2e/
├── public/
├── start.js
└── package.json
```

## Troubleshooting

### Backend does not start

- verify the Python environment and dependencies are installed
- use `pip install academic-refchecker[webui]` or `pip install -e ".[llm,webui]"`

### Frontend does not start

- verify `node --version` is 20.19+
- reinstall dependencies with `rm -rf node_modules && npm install`

### PDF extraction is limited

- configure an extraction LLM provider for best results
- if running without an LLM, verify GROBID is reachable at `GROBID_URL`
- if you expect Docker auto-start, verify Docker is installed and usable by the current user

### Hallucination checks are missing

- configure a hallucination-capable provider in Settings: OpenAI, Anthropic, Google, or Azure
- make sure the selected hallucination configuration has an API key in the current mode
- extraction can succeed through GROBID or vLLM without enabling deep hallucination verification
