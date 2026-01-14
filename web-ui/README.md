# RefChecker Web UI

A modern, real-time web interface for validating academic paper references.

## Features

- ✨ **Real-time Validation** - Live progress updates via WebSockets as references are checked
- 📄 **Multiple Input Methods** - Support for ArXiv URLs, file uploads (PDF, LaTeX, text)
- 📊 **Live Statistics** - Real-time summary panel with progress bar and error counts
- 🔗 **Authoritative Links** - Clickable hyperlinks to Semantic Scholar, ArXiv, and DOI
- 📚 **Check History** - Persistent storage of all checks with ability to view and re-run
- ⚡ **Fast & Responsive** - Modern React UI with TailwindCSS
- 🤖 **LLM-Powered** - Uses AI for accurate reference extraction
- 📋 **Export Options** - Copy references as Markdown, plain text, or BibTeX
- 🌓 **Dark/Light Mode** - Automatic theme based on system preference
- 🧪 **Fully Tested** - Comprehensive E2E tests with Playwright

## Quick Start

### Prerequisites

- **Python 3.8+** with RefChecker installed:
  ```bash
  pip install academic-refchecker[llm,webui]
  ```
- **Node.js 18+** and npm
- **LLM API Key** (Anthropic or OpenAI recommended)

### One-Command Launch

```bash
cd web-ui
npm install    # First time only
npm start      # Starts both backend and frontend
```

Options:
- `npm start` - Start servers (skips if already running)
- `npm run restart` - Kill existing servers and restart fresh

This will:
1. Start the FastAPI backend on **http://localhost:8000**
2. Start the Vite frontend on **http://localhost:5173**
3. Open your browser to the web interface

### Manual Launch

If you prefer to run servers separately:

**Terminal 1 - Backend:**
```bash
cd backend
python main.py
```

**Terminal 2 - Frontend:**
```bash
cd web-ui
npm run dev
```

## Usage

### Checking a Paper

**Option 1: Using ArXiv ID/URL**
1. Enter an ArXiv ID (e.g., `1706.03762`) or URL
2. Click "Check References"
3. Watch real-time progress as references are validated

**Option 2: Uploading a File**
1. Click the upload area or drag-and-drop a file
2. Supported formats: PDF, LaTeX (.tex), text (.txt)
3. Click "Check References"
4. View results as they stream in

### Understanding Results

Results appear in real-time with status indicators:

| Icon | Status | Description |
|------|--------|-------------|
| ✓ | Verified | Reference matches authoritative sources |
| ✗ | Error | Critical mismatch (author, title, DOI, etc.) |
| ⚠ | Warning | Minor issue (year, venue format) |
| ↑ | Suggestion | Recommended improvement (e.g., add arXiv link) |
| ? | Unverified | Could not verify against any source |

Each reference shows:
- Title, authors, year, venue
- Clickable links to Semantic Scholar, ArXiv, DOI
- Detailed error/warning messages with cited vs. actual values

### Exporting References

Click the copy icon on any reference card to export as:
- **Markdown** - Formatted with bold/italic
- **Plain Text** - Standard ACM citation format
- **BibTeX** - Ready for LaTeX documents

Exports use **corrected values** from verification when available.

### Check History

- View all past checks in the left sidebar
- Click any check to view full results
- Edit check titles for organization
- Delete checks you no longer need
- History persists across sessions (stored in SQLite)

## Configuration

### Environment Variables

Set these before running:

```bash
# Required: At least one LLM API key
export ANTHROPIC_API_KEY=your_key_here
# or
export OPENAI_API_KEY=your_key_here

# Optional: For faster verification (1-2s vs 5-10s per reference)
export SEMANTIC_SCHOLAR_API_KEY=your_key_here
```

### LLM Provider

The web UI supports multiple LLM providers. Configure via the settings panel in the sidebar.

## Architecture

```
┌─────────────────┐          ┌──────────────────┐
│   React + Vite  │ ◄──WS──► │  FastAPI Backend │
│   (Frontend)    │          │                  │
│   Port: 5173    │          │  Port: 8000      │
└─────────────────┘          └──────────────────┘
                                      │
                                      ├─► RefChecker Core Library
                                      └─► SQLite Database
```

## Project Structure

```
web-ui/
├── src/
│   ├── components/          # React components
│   │   ├── MainPanel/       # Input, stats, reference list
│   │   ├── Sidebar/         # History, settings
│   │   └── ReferenceCard/   # Individual reference display
│   ├── stores/              # Zustand state management
│   ├── utils/               # API, WebSocket, formatters
│   └── App.jsx              # Main application
├── e2e/                     # Playwright E2E tests
├── public/                  # Static assets
├── start.js                 # Launch script (cross-platform Node.js)
└── package.json
```

## Development

### Running Tests

```bash
# Unit tests
npm test

# E2E tests (headless)
npm run test:e2e

# E2E tests (with browser UI)
npm run test:e2e:ui
```

### Building for Production

```bash
npm run build    # Creates dist/ directory
```

Serve the built files with any static file server, pointing API requests to the backend.

## API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/check` | Start new check (file upload or URL) |
| GET | `/api/history` | Get check history |
| GET | `/api/history/{id}` | Get specific check results |
| POST | `/api/recheck/{id}` | Re-run a previous check |
| DELETE | `/api/history/{id}` | Delete history entry |
| PUT | `/api/history/{id}` | Update check (e.g., title) |
| GET | `/api/llm-configs` | Get saved LLM configurations |

### WebSocket

Connect to `WS /api/ws/{session_id}` for real-time updates.

Message types:
- `started` - Check initiated
- `extracting` - Extracting references from document
- `progress` - Current progress (N of M references)
- `reference_result` - Individual reference result
- `summary_update` - Updated statistics
- `completed` - Check complete with final summary
- `error` - Error occurred

## Troubleshooting

### Backend won't start
- Check Python virtual environment is activated
- Install dependencies: `pip install academic-refchecker[webui]` or `pip install -r requirements.txt`
- Check API key is set in environment

### Frontend won't start
- Check Node.js version: `node --version` (should be 18+)
- Clear and reinstall: `rm -rf node_modules && npm install`

### WebSocket connection fails
- Ensure backend is running on port 8000
- Check browser console for CORS errors
- Try refreshing the page

### Slow verification
- Get a Semantic Scholar API key for 5x faster verification
- Set `SEMANTIC_SCHOLAR_API_KEY` environment variable

## License

MIT License - see main project [LICENSE](../LICENSE)
