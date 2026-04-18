# RefChecker Web UI

This guide is the canonical reference for the Web UI.

## Overview

The Web UI provides a real-time interface for checking references in single papers and batches. It includes history, exports, per-reference diagnostics, and hosted multi-user support.

## Extraction Behavior

- If an LLM provider is configured, RefChecker uses it for higher-quality extraction from PDFs and unusual bibliography formats.
- If no LLM is configured, PDF extraction can fall back to GROBID.
- Hallucination web-search checks require an LLM provider even when extraction succeeds through GROBID.

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

- Python 3.8+
- Node.js 18+
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

LLM providers are optional for extraction but required for hallucination web-search checks.

```bash
export ANTHROPIC_API_KEY=your_key_here
# or
export OPENAI_API_KEY=your_key_here
# or
export GOOGLE_API_KEY=your_key_here
```

Optional configuration:

```bash
export GROBID_URL=http://localhost:8070
```

The Semantic Scholar API key is entered in the UI settings panel and stays in browser memory for the current tab.

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

- verify `node --version` is 18+
- reinstall dependencies with `rm -rf node_modules && npm install`

### PDF extraction is limited

- configure an LLM provider for best results
- if running without an LLM, verify GROBID is reachable at `GROBID_URL`
- if you expect Docker auto-start, verify Docker is installed and usable by the current user

### Hallucination checks are missing

- configure an LLM provider in Settings
- extraction can succeed through GROBID without enabling hallucination web-search verification