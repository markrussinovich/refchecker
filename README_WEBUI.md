# RefChecker Web UI

A modern, real-time web interface for validating academic paper references.

## Features

✨ **Real-time Validation** - Live progress updates via WebSockets as references are checked
📄 **Multiple Input Methods** - Support for ArXiv URLs, file uploads (PDF, LaTeX, text)
📊 **Live Statistics** - Real-time summary panel with progress bar and error counts
🔗 **Authoritative Links** - Clickable hyperlinks to Semantic Scholar, ArXiv, and DOI
📚 **Check History** - Persistent storage of all checks with ability to view and re-run
⚡ **Fast & Responsive** - Modern React UI with TailwindCSS
🤖 **LLM-Powered** - Uses Anthropic Claude for accurate reference extraction
🧪 **Fully Tested** - Comprehensive E2E tests with Playwright

## Architecture

```
┌─────────────────┐          ┌──────────────────┐
│   React + Vite  │ ◄──WS──► │  FastAPI Backend │
│   (Frontend)    │          │                  │
│   Port: 5173    │          │  Port: 8000      │
└─────────────────┘          └──────────────────┘
                                      │
                                      ├─► RefChecker Lib
                                      └─► SQLite Database
```

## Prerequisites

- Python 3.7+ with virtual environment
- Node.js 18+ and npm
- Anthropic API key (set as `ANTHROPIC_API_KEY` environment variable)

## Quick Start

### 1. Backend Setup

```bash
# Activate virtual environment
cd refchecker
.venv\Scripts\activate  # Windows
# or
source .venv/bin/activate  # Linux/Mac

# Install backend dependencies (if not already done)
pip install fastapi uvicorn[standard] python-multipart websockets aiosqlite

# Start the backend server
cd backend
python main.py
```

Backend will run at: **http://localhost:8000**

### 2. Frontend Setup

```bash
# Open new terminal
cd refchecker/web-ui

# Install dependencies (if not already done)
npm install

# Start development server
npm run dev
```

Frontend will run at: **http://localhost:5173**

### 3. Access the Application

Open your browser to: **http://localhost:5173**

## Usage

### Checking a Paper

**Option 1: Using ArXiv ID/URL**
1. Click "URL/ArXiv ID" button
2. Enter an ArXiv ID (e.g., `1706.03762`) or URL
3. Click "Check References"
4. Watch real-time progress as references are validated

**Option 2: Uploading a File**
1. Click "Upload File" button
2. Select a PDF, LaTeX (.tex), or text (.txt) file
3. Click "Check References"
4. View results as they stream in

### Viewing Results

Results appear in real-time with:
- **✓ Verified** - Reference matches authoritative sources
- **✗ Errors** - Critical mismatches (author, title, DOI, etc.)
- **⚠ Warnings** - Minor issues (year, venue format)
- **? Unverified** - Could not verify against any source

Each reference shows:
- Title, authors, year, venue
- Clickable links to:
  - 📚 Semantic Scholar
  - 📄 ArXiv
  - 🔗 DOI
- Detailed error/warning messages with cited vs. actual values

### Check History

- View all past checks in the left sidebar
- Click any check to view full results
- Click "Re-check" to run validation again
- History persists across sessions (stored in SQLite)

## Testing

### Run E2E Tests with Playwright

```bash
cd web-ui

# Run tests in headless mode
npm run test:e2e

# Run tests in UI mode (interactive)
npx playwright test --ui

# Run tests in headed mode (see browser)
npx playwright test --headed
```

### Test Coverage

The test suite includes:
- ✓ Homepage loading and basic UI
- ✓ Input mode switching (URL/File)
- ✓ Form validation
- ✓ History loading and display
- ✓ Viewing check details
- ✓ Summary statistics display
- ✓ Reference cards with errors/warnings
- ✓ Authoritative URL links
- ✓ Re-check functionality

## Project Structure

```
refchecker/
├── backend/
│   ├── main.py                    # FastAPI application
│   ├── refchecker_wrapper.py      # RefChecker with progress callbacks
│   ├── websocket_manager.py       # WebSocket connection manager
│   ├── database.py                # SQLite database handler
│   └── models.py                  # Pydantic models
│
├── web-ui/
│   ├── src/
│   │   ├── App.jsx                # Main React component
│   │   ├── utils/api.js           # API and WebSocket utilities
│   │   └── index.css              # TailwindCSS styles
│   ├── e2e/
│   │   └── refchecker.spec.js     # Playwright E2E tests
│   ├── playwright.config.js       # Playwright configuration
│   └── package.json
│
├── WEBUI_IMPLEMENTATION.md        # Implementation guide
└── README_WEBUI.md               # This file
```

## API Endpoints

### REST Endpoints
- `POST /api/check` - Start new check (file upload or URL)
- `GET /api/history` - Get check history
- `GET /api/history/{id}` - Get specific check results
- `POST /api/recheck/{id}` - Re-run a previous check
- `DELETE /api/history/{id}` - Delete history entry

### WebSocket
- `WS /api/ws/{session_id}` - Real-time updates

### WebSocket Message Types
- `started` - Check initiated
- `extracting` - Extracting references
- `progress` - Current progress (N/M references)
- `reference_result` - Individual reference result
- `summary_update` - Updated statistics
- `completed` - Check complete with final summary
- `error` - Error occurred

## Configuration

### Environment Variables

Create `.env` file in backend directory:

```env
ANTHROPIC_API_KEY=your_api_key_here
SEMANTIC_SCHOLAR_API_KEY=your_key_here  # Optional, for higher rate limits
```

### LLM Provider

Currently configured for Anthropic Claude. To change:

Edit `web-ui/src/App.jsx` line 71:
```javascript
formData.append('llm_provider', 'anthropic'); // Change to 'openai', 'google', etc.
```

## Troubleshooting

### Backend won't start
- Check Python virtual environment is activated
- Verify all dependencies installed: `pip install -r requirements.txt`
- Check `ANTHROPIC_API_KEY` environment variable is set

### Frontend won't start
- Check Node.js version: `node --version` (should be 18+)
- Clear node_modules and reinstall: `rm -rf node_modules && npm install`

### WebSocket connection fails
- Ensure backend is running on port 8000
- Check browser console for connection errors
- Verify CORS settings in `backend/main.py`

### Tests fail
- Ensure both frontend and backend are not already running
- Run `npx playwright install chromium` to ensure browser is installed
- Check `playwright.config.js` configuration

## Development

### Adding New Features

1. **Backend**: Add route to `backend/main.py`
2. **Frontend**: Update `App.jsx` and `utils/api.js`
3. **Tests**: Add E2E tests to `e2e/refchecker.spec.js`

### Building for Production

```bash
# Frontend
cd web-ui
npm run build  # Creates dist/ directory

# Backend
# Use production ASGI server like gunicorn with uvicorn workers
pip install gunicorn
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

## Performance

- **Reference extraction**: 5-15 seconds depending on paper length and LLM
- **Reference verification**: 1-2 seconds per reference (with Semantic Scholar API key)
- **WebSocket latency**: <100ms for real-time updates
- **History loading**: <1 second for 50 recent checks

## Known Limitations

- ArXiv downloads require internet connection
- LLM extraction quality depends on paper format
- Rate limiting on verification APIs (use API keys for better performance)
- Large papers (>100 references) may take several minutes

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Submit a pull request

## License

MIT License - see main README.md

## Support

For issues or questions:
- Check `WEBUI_IMPLEMENTATION.md` for implementation details
- Review test suite for usage examples
- Open an issue on GitHub

## Example: Testing with "Attention Is All You Need"

Try the famous transformer paper:
1. Enter ArXiv ID: `1706.03762`
2. Click "Check References"
3. Watch ~45 references being validated in real-time
4. View errors, warnings, and authoritative links
5. Check persists in history for future reference

---

**Built with:** React, Vite, TailwindCSS, FastAPI, WebSockets, Playwright, SQLite, and RefChecker
