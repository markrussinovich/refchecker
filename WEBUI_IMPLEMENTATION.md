# RefChecker Web UI - Implementation Guide

## Project Overview

A local web UI for RefChecker that provides real-time reference validation with:
- React + Vite + TailwindCSS frontend
- FastAPI + WebSockets backend
- SQLite for persistent history
- Real-time progress updates
- Check history with re-check capability

## Project Structure

```
refchecker/
├── backend/
│   ├── __init__.py
│   ├── main.py                    # FastAPI application (TO CREATE)
│   ├── refchecker_wrapper.py      # Wrapper around refchecker lib (TO CREATE)
│   ├── websocket_manager.py       # ✅ WebSocket manager
│   ├── models.py                  # ✅ Pydantic models
│   └── database.py                # ✅ SQLite database handler
├── web-ui/
│   ├── src/
│   │   ├── components/
│   │   │   ├── InputForm.jsx
│   │   │   ├── ValidationResults.jsx
│   │   │   ├── ReferenceCard.jsx
│   │   │   ├── SummaryPanel.jsx
│   │   │   ├── HistorySidebar.jsx
│   │   │   └── ErrorDisplay.jsx
│   │   ├── hooks/
│   │   │   ├── useWebSocket.js
│   │   │   └── useRefChecker.js
│   │   ├── utils/
│   │   │   └── api.js
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   └── tailwind.config.js         # ✅ Configured
└── README_WEBUI.md                # Usage instructions

```

## Implementation Status

### ✅ Completed
1. React project setup with Vite
2. TailwindCSS configuration
3. Database module (SQLite)
4. Pydantic models
5. WebSocket manager
6. Python dependencies installed

### 🚧 Remaining Tasks
1. Create `backend/refchecker_wrapper.py` - Wraps refchecker lib with progress callbacks
2. Create `backend/main.py` - FastAPI app with all endpoints
3. Create all React components
4. Create React hooks for WebSocket and API
5. Test with sample paper (1706.03762)
6. Polish UX and responsive design

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
- `error` - Error occurred (LLM or processing)

## Running the Application

### Backend
```bash
cd refchecker
.venv\Scripts\activate
cd backend
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd refchecker/web-ui
npm run dev
```

Access at: http://localhost:5173

## Key Features

### 1. Input Handling
- URL input for ArXiv papers
- File upload for PDF, .tex, .txt files
- Drag-and-drop support
- Input validation

### 2. Real-time Updates
- Live progress bar
- Reference-by-reference results streaming
- Summary statistics updates in real-time
- Clear completion indicator

### 3. Results Display
- Reference cards with expandable details
- Status icons (✓ ❌ ⚠️ ❓)
- Clickable hyperlinks to:
  - Semantic Scholar
  - ArXiv
  - DOI
  - Other authoritative sources
- Error/warning details
- Corrected reference suggestions

### 4. Check History
- Sidebar with past checks
- Paper title + timestamp
- Summary stats per check
- Click to view full results
- Re-check button
- Delete option

### 5. Error Reporting
- LLM API errors with provider info
- File processing errors
- Network errors
- Suggested actions

## Database Schema

```sql
CREATE TABLE check_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_title TEXT NOT NULL,
    paper_source TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_refs INTEGER,
    errors_count INTEGER,
    warnings_count INTEGER,
    unverified_count INTEGER,
    results_json TEXT,
    llm_provider TEXT,
    llm_model TEXT,
    status TEXT DEFAULT 'completed'
);
```

## Next Steps

1. **Create refchecker_wrapper.py**
   - Import refchecker core functionality
   - Add progress callback mechanism
   - Convert results to API format

2. **Create main.py FastAPI app**
   - Implement all REST endpoints
   - Add WebSocket endpoint
   - CORS configuration for local dev
   - File upload handling

3. **Build React Components**
   - Start with App.jsx layout
   - InputForm with validation
   - SummaryPanel with live stats
   - ReferenceCard with hyperlinks
   - HistorySidebar with click handlers

4. **Create React Hooks**
   - useWebSocket for connection management
   - useRefChecker for API calls

5. **Integration Testing**
   - Test with ArXiv paper 1706.03762
   - Verify real-time updates
   - Test history persistence
   - Test re-check functionality

6. **Polish**
   - Responsive design
   - Loading states
   - Error boundaries
   - Accessibility

## Development Notes

- Backend uses async/await for non-blocking operations
- WebSocket messages are JSON-formatted
- File uploads are streamed to temp directory
- SQLite database is created automatically on first run
- Frontend uses Vite proxy for API calls (configure in vite.config.js)

## Environment Variables

Backend (.env):
```
ANTHROPIC_API_KEY=your_key_here
SEMANTIC_SCHOLAR_API_KEY=your_key_here  # Optional
```

## Testing Paper

Use ArXiv ID: 1706.03762 (Attention Is All You Need)
- Well-known paper
- ~45 references
- Good mix of verified/errors/warnings for demo
