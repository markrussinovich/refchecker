# RefChecker

Validate reference accuracy in academic papers. Useful for authors checking bibliographies and reviewers ensuring citations are authentic. RefChecker verifies citations against Semantic Scholar, OpenAlex, and CrossRef.

*Built by Mark Russinovich with AI assistants (Cursor, GitHub Copilot, Claude Code). [Watch the deep dive video](https://www.youtube.com/watch?v=n929Alz-fjo).*

## Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [Sample Output](#sample-output)
- [Install](#install)
- [Run](#run)
- [Output](#output)
- [Configure](#configure)
- [Docker](#docker)
- [Local Database](#local-database)
- [Testing](#testing)
- [License](#license)

## Quick Start

### Web UI (Docker)

```bash
docker run -p 8000:8000 ghcr.io/markrussinovich/refchecker:latest
```

Open **http://localhost:8000** in your browser.

### Web UI (pip)

```bash
pip install academic-refchecker[llm,webui]
refchecker-webui
```

### CLI (pip)

```bash
pip install academic-refchecker[llm]
academic-refchecker --paper 1706.03762
academic-refchecker --paper /path/to/paper.pdf
```

> **Performance**: Set `SEMANTIC_SCHOLAR_API_KEY` for 1-2s per reference vs 5-10s without.

## Features

- **Multiple formats**: ArXiv papers, PDFs, LaTeX, text files
- **LLM-powered extraction**: OpenAI, Anthropic, Google, Azure, vLLM
- **Multi-source verification**: Semantic Scholar, OpenAlex, CrossRef
- **Comprehensive checks**: Titles, authors, years, venues, DOIs, ArXiv IDs
- **Smart matching**: Handles formatting variations (BERT vs B-ERT, pre-trained vs pretrained)
- **Detailed reports**: Errors, warnings, corrected references

## Sample Output

**Web UI**

![RefChecker Web UI](assets/webui.png)

**CLI**

```
📄 Processing: Attention Is All You Need
   URL: https://arxiv.org/abs/1706.03762

[1/45] Neural machine translation in linear time
       Nal Kalchbrenner et al. | 2017
       ⚠️  Warning: Year mismatch: cited '2017', actual '2016'

[2/45] Effective approaches to attention-based neural machine translation
       Minh-Thang Luong et al. | 2015
       ❌ Error: First author mismatch: cited 'Minh-Thang Luong', actual 'Thang Luong'

[3/45] Deep Residual Learning for Image Recognition
       Kaiming He et al. | 2016 | https://doi.org/10.1109/CVPR.2016.91
       ❌ Error: DOI mismatch: cited '10.1109/CVPR.2016.91', actual '10.1109/CVPR.2016.90'

============================================================
📋 SUMMARY
📚 Total references processed: 68
❌ Total errors: 55  ⚠️ Total warnings: 16  ❓ Unverified: 15
```

## Install

### PyPI (Recommended)

```bash
pip install academic-refchecker[llm,webui]  # Web UI + CLI + LLM providers
pip install academic-refchecker             # CLI only
```

### From Source (Development)

```bash
git clone https://github.com/markrussinovich/refchecker.git && cd refchecker
python -m venv .venv && source .venv/bin/activate
pip install -e ".[llm,webui]"
```

**Requirements:** Python 3.7+ (3.10+ recommended). Node.js 18+ is only needed for Web UI development.

## Run

### Web UI

The Web UI shows live progress, history, and export (including corrected values).

```bash
refchecker-webui --port 8000
```

#### Development (frontend)

```bash
cd web-ui
npm install
npm start
```

Open **http://localhost:5173**.

Alternative (separate servers):

```bash
# Terminal 1
python -m uvicorn backend.main:app --reload --port 8000

# Terminal 2
cd web-ui
npm run dev
```

Verify the backend is running:

```bash
curl http://localhost:8000/
```

Web UI documentation: see [web-ui/README.md](web-ui/README.md).

### CLI

```bash
# ArXiv (ID or URL)
academic-refchecker --paper 1706.03762
academic-refchecker --paper https://arxiv.org/abs/1706.03762

# Local files
academic-refchecker --paper paper.pdf
academic-refchecker --paper paper.tex
academic-refchecker --paper paper.txt
academic-refchecker --paper refs.bib

# Faster/offline verification (local DB)
academic-refchecker --paper paper.pdf --db-path semantic_scholar_db/semantic_scholar.db

# Save results
academic-refchecker --paper 1706.03762 --output-file errors.txt
```

## Output

RefChecker reports these result types:

| Type | Description | Examples |
|------|-------------|----------|
| ❌ **Error** | Critical issues needing correction | Author/title/DOI mismatches, incorrect ArXiv IDs |
| ⚠️ **Warning** | Minor issues to review | Year differences, venue variations |
| ℹ️ **Suggestion** | Recommended improvements | Add missing ArXiv/DOI URLs, small metadata fixes |
| ❓ **Unverified** | Could not verify against any source | Rare publications, preprints |

Verified references include discovered URLs (Semantic Scholar, ArXiv, DOI). Suggestions are non-blocking improvements.

<details>
<summary>Detailed examples</summary>

```
❌ Error: First author mismatch: cited 'T. Xie', actual 'Zhao Xu'
❌ Error: DOI mismatch: cited '10.5555/3295222.3295349', actual '10.48550/arXiv.1706.03762'
⚠️ Warning: Year mismatch: cited '2024', actual '2023'
ℹ️ Suggestion: Add ArXiv URL https://arxiv.org/abs/1706.03762
❓ Could not verify: Llama guard (M. A. Research, 2024)
```

</details>

## Configure

### LLM

LLM-powered extraction improves accuracy with complex bibliographies. Claude Sonnet 4 performs best; GPT-4o may hallucinate DOIs.

| Provider | Env Variable | Example Model |
|----------|--------------|---------------|
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-20250514` |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o` |
| Google | `GOOGLE_API_KEY` | `gemini-2.5-flash` |
| Azure | `AZURE_OPENAI_API_KEY` | `gpt-4` |
| vLLM | (local) | `meta-llama/Llama-3.1-8B-Instruct` |

```bash
export ANTHROPIC_API_KEY=your_key
academic-refchecker --paper 1706.03762 --llm-provider anthropic

academic-refchecker --paper paper.pdf --llm-provider openai --llm-model gpt-4o
academic-refchecker --paper paper.pdf --llm-provider vllm --llm-model meta-llama/Llama-3.1-8B-Instruct
```

#### Local models (vLLM)

There is no separate “GPU Docker image”. For local inference, install the vLLM extra and run an OpenAI-compatible vLLM server:

```bash
pip install "academic-refchecker[vllm]"
python scripts/start_vllm_server.py --model meta-llama/Llama-3.1-8B-Instruct --port 8001
academic-refchecker --paper paper.pdf --llm-provider vllm --llm-endpoint http://localhost:8001/v1
```

### Command Line

```bash
--paper PAPER              # ArXiv ID, URL, or file path
--llm-provider PROVIDER    # openai, anthropic, google, azure, vllm
--llm-model MODEL          # Override default model
--db-path PATH             # Local database for offline verification
--output-file [PATH]       # Save results (default: reference_errors.txt)
--debug                    # Verbose output
```

### Environment Variables

```bash
# LLM
export REFCHECKER_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=your_key           # Also: OPENAI_API_KEY, GOOGLE_API_KEY

# Performance
export SEMANTIC_SCHOLAR_API_KEY=your_key    # Higher rate limits / faster verification
```

## Docker

Pre-built images are published to GitHub Container Registry.

```bash
docker run -p 8000:8000 \
       -e ANTHROPIC_API_KEY=your_key \
       -v refchecker-data:/app/data \
       ghcr.io/markrussinovich/refchecker:latest
```

Docker Compose:

```bash
git clone https://github.com/markrussinovich/refchecker.git && cd refchecker
cp .env.example .env  # Add your API keys
docker compose up -d
```

| Tag | Description | Arch | Size |
|-----|-------------|------|------|
| `latest` | RefChecker (Web UI + API-based LLM support) | amd64, arm64 | ~800MB |

## Local Database

For offline verification or faster processing:

```bash
python scripts/download_db.py \
  --field "computer science" \
  --start-year 2020 --end-year 2024

academic-refchecker --paper paper.pdf --db-path semantic_scholar_db/semantic_scholar.db
```

## Testing

490+ tests covering unit, integration, and end-to-end scenarios.

```bash
pytest tests/                    # All tests
pytest tests/unit/              # Unit only
pytest --cov=src tests/         # With coverage
```

See [tests/README.md](tests/README.md) for details.

## License

MIT License - see [LICENSE](LICENSE).
