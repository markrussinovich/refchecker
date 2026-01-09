# RefChecker Web UI - Planning Document

> **Living Document** - Updated as decisions are made and implementation progresses.
> 
> **Last Updated**: January 8, 2026

## Overview

A fresh React-based web UI for RefChecker with:
- Left sidebar for LLM configuration and check history
- Main panel for paper input, status, stats, and reference results
- Real-time WebSocket updates during checking
- Dark/light theme support
- Comprehensive Playwright and unit testing

## Architecture

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | React 19 + Vite + TailwindCSS 4 | UI components, styling |
| State | Zustand | Global state management |
| Backend | FastAPI (augmented) | REST API + WebSocket endpoints |
| Database | SQLite (server-side) | History, LLM configs with AES-256 encrypted API keys |
| Testing | Playwright + Vitest | E2E + unit tests |

## Deployment Model

- **Local**: Run locally on user's machine
- **Hosted**: Can be deployed as a service for multiple users
- Both models supported; authentication can be added later for hosted mode

## Design Decisions

| Decision | Resolution | Date |
|----------|------------|------|
| Existing UI | Rebuild from scratch (user choice A) | 2026-01-08 |
| API Key Storage | AES-256 encrypted with server-managed key | 2026-01-08 |
| History Storage | Server-side SQLite (global for now) | 2026-01-08 |
| File Size Limit | 200MB with clear error messaging | 2026-01-08 |
| History Features | Delete + edit label (defaults to paper title) | 2026-01-08 |

---

## Database Schema

### Existing Table: `check_history` (Modified)

```sql
CREATE TABLE check_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_title TEXT NOT NULL,
    paper_source TEXT NOT NULL,
    source_type TEXT DEFAULT 'url',
    custom_label TEXT,                    -- NEW: User-editable display name
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

### New Table: `llm_configs`

```sql
CREATE TABLE llm_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                   -- User-friendly display name
    provider TEXT NOT NULL,               -- openai, anthropic, google, azure, vllm
    model TEXT,                           -- Model override (null = use default)
    api_key_encrypted TEXT,               -- AES-256 encrypted API key
    endpoint TEXT,                        -- For Azure/vLLM
    is_default BOOLEAN DEFAULT 0,         -- Currently selected config
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## API Endpoints

### LLM Configuration (New)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/llm-configs` | GET | List all configs (API keys redacted) |
| `/api/llm-configs` | POST | Create new LLM config |
| `/api/llm-configs/{id}` | PUT | Update config (re-encrypt if key changed) |
| `/api/llm-configs/{id}` | DELETE | Delete config |
| `/api/llm-configs/{id}/set-default` | POST | Set as default LLM |

### History (Modified)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/history` | GET | List history (existing) |
| `/api/history/{id}` | GET | Get check details (existing) |
| `/api/history/{id}` | DELETE | Delete check (existing) |
| `/api/history/{id}` | PATCH | Update custom label (new) |
| `/api/recheck/{id}` | POST | Re-run check (existing) |

### Check Operations (Existing)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/check` | POST | Start new check |
| `/api/cancel/{session_id}` | POST | Cancel active check |
| `/ws/{session_id}` | WebSocket | Real-time updates |

---

## LLM Provider Configuration

Following CLI conventions from `src/refchecker/config/`:

| Provider | Default Model | Required Fields |
|----------|---------------|-----------------|
| `openai` | `gpt-4.1` | API key |
| `anthropic` | `claude-sonnet-4-20250514` | API key |
| `google` | `gemini-2.5-flash` | API key |
| `azure` | `gpt-4o` | API key + endpoint |
| `vllm` | `meta-llama/Llama-3.1-8B-Instruct` | endpoint (no API key) |

---

## Component Structure

```
web-ui/src/
├── components/
│   ├── Sidebar/
│   │   ├── Sidebar.jsx          # Container
│   │   ├── LLMSelector.jsx      # Dropdown + add/delete
│   │   ├── LLMConfigModal.jsx   # Add/edit LLM form
│   │   ├── HistoryList.jsx      # Scrollable history
│   │   └── HistoryItem.jsx      # Individual item with edit/delete
│   ├── MainPanel/
│   │   ├── MainPanel.jsx        # Container
│   │   ├── InputSection.jsx     # URL/file input + Check button
│   │   ├── FileDropZone.jsx     # Drag-drop handler
│   │   ├── StatusSection.jsx    # Progress + status messages
│   │   ├── StatsSection.jsx     # Summary cards
│   │   └── ReferenceList.jsx    # Reference entries
│   ├── ReferenceCard/
│   │   ├── ReferenceCard.jsx    # Individual reference
│   │   ├── StatusIndicator.jsx  # Spinner/icons
│   │   └── ErrorDetails.jsx     # Expandable errors
│   └── common/
│       ├── ThemeToggle.jsx      # Dark/light switch
│       ├── Modal.jsx            # Reusable modal
│       └── Button.jsx           # Styled button variants
├── stores/
│   ├── useConfigStore.js        # LLM configs + selected
│   ├── useHistoryStore.js       # Check history
│   └── useCheckStore.js         # Current check state
├── hooks/
│   ├── useWebSocket.js          # WebSocket connection
│   └── useFileUpload.js         # Drag-drop + validation
├── utils/
│   ├── api.js                   # REST API calls
│   ├── formatters.js            # Date, reference formatting
│   └── logger.js                # Console logging with levels
├── App.jsx                      # Layout + theme provider
├── main.jsx                     # Entry point
└── index.css                    # Tailwind + theme variables
```

---

## UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                         Header (Theme Toggle)                    │
├────────────────┬────────────────────────────────────────────────┤
│                │                                                 │
│   LLM Config   │              Input Section                      │
│   [Dropdown]   │   ┌─────────────────────────────────────────┐  │
│   + Add/Delete │   │ ArXiv ID / URL / Drag file here         │  │
│                │   └─────────────────────────────────────────┘  │
│ ───────────────│   [ Check ] / [ Cancel ]                       │
│                │                                                 │
│   History      │ ────────────────────────────────────────────── │
│                │                                                 │
│ ┌────────────┐ │              Status Section                     │
│ │ Paper Title│ │   Extracting references... (3/15 checked)      │
│ │ 2026-01-08 │ │   [████████░░░░░░░░] 53%                       │
│ └────────────┘ │                                                 │
│ ┌────────────┐ │ ────────────────────────────────────────────── │
│ │ Paper Title│ │                                                 │
│ │ 2026-01-07 │ │              Stats Section                      │
│ └────────────┘ │   ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐     │
│                │   │Total│ │  ✓  │ │  ⚠  │ │  ✗  │ │  ?  │     │
│ (scrollable)   │   │ 15  │ │ 10  │ │  2  │ │  1  │ │  2  │     │
│                │   └─────┘ └─────┘ └─────┘ └─────┘ └─────┘     │
│                │                                                 │
│                │ ────────────────────────────────────────────── │
│                │                                                 │
│                │              References List                    │
│                │   ┌───────────────────────────────────────┐    │
│                │   │ 1. Smith et al. (2023) "Paper Title"  │    │
│                │   │    ⏳ Checking...                      │    │
│                │   └───────────────────────────────────────┘    │
│                │   ┌───────────────────────────────────────┐    │
│                │   │ 2. Jones (2022) "Another Paper"   ✓   │    │
│                │   │    ▸ View details                      │    │
│                │   └───────────────────────────────────────┘    │
│                │                                                 │
└────────────────┴────────────────────────────────────────────────┘
```

---

## WebSocket Message Types

| Type | Payload | UI Action |
|------|---------|-----------|
| `started` | `{ session_id }` | Show "Starting..." status |
| `extracting` | `{ message }` | Show "Extracting references..." |
| `references_extracted` | `{ count, references[] }` | Populate reference list |
| `checking_reference` | `{ index, total }` | Update status "Checking N/M" |
| `reference_result` | `{ reference }` | Update reference card with result |
| `summary_update` | `{ stats }` | Update stats section |
| `progress` | `{ percent }` | Update progress bar |
| `completed` | `{ check_id }` | Show completion, add to history |
| `cancelled` | `{}` | Show "Cancelled", enable restart |
| `error` | `{ message }` | Show error message |

---

## Theme System

Using CSS variables with Tailwind's `dark:` variant:

```css
:root {
  --color-bg-primary: #ffffff;
  --color-bg-secondary: #f3f4f6;
  --color-text-primary: #111827;
  --color-text-secondary: #6b7280;
  --color-accent: #3b82f6;
  --color-error: #ef4444;
  --color-warning: #f59e0b;
  --color-success: #10b981;
}

.dark {
  --color-bg-primary: #111827;
  --color-bg-secondary: #1f2937;
  --color-text-primary: #f9fafb;
  --color-text-secondary: #9ca3af;
  --color-accent: #60a5fa;
  --color-error: #f87171;
  --color-warning: #fbbf24;
  --color-success: #34d399;
}
```

---

## Testing Strategy

### Playwright E2E Tests

1. **Sidebar - LLM Configuration**
   - Add new LLM config
   - Select LLM from dropdown
   - Delete LLM config
   - Verify API key is not displayed after save

2. **Sidebar - History**
   - View history list
   - Click item to load results
   - Edit item label
   - Delete item

3. **Main Panel - Input**
   - Enter ArXiv ID
   - Enter URL
   - Upload file via button
   - Drag-drop file
   - Validate 200MB limit

4. **Main Panel - Check Flow**
   - Start check
   - Verify status updates
   - Cancel mid-check
   - Restart after cancel
   - Complete check

5. **Main Panel - Results**
   - Verify reference cards appear
   - Expand reference details
   - Click authoritative URLs
   - Verify stats update in real-time

6. **Theme**
   - Toggle dark/light mode
   - Verify persistence

### Vitest Unit Tests

1. **Stores** - State management logic
2. **Utils** - API calls, formatters
3. **Hooks** - WebSocket, file upload
4. **Components** - Render tests, user interactions

---

## Implementation Phases

### Phase 1: Foundation ✅ In Progress
- [x] Create PLANNING.md
- [ ] Set up React project with Vite + Tailwind
- [ ] Configure theme system
- [ ] Create base layout (Sidebar + MainPanel)

### Phase 2: Backend Augmentation
- [ ] Add `llm_configs` table
- [ ] Add `custom_label` to `check_history`
- [ ] Implement LLM config CRUD endpoints
- [ ] Implement history PATCH endpoint
- [ ] Add AES-256 encryption for API keys

### Phase 3: Sidebar Implementation
- [ ] LLM selector dropdown
- [ ] Add/edit LLM modal
- [ ] History list with edit/delete
- [ ] Connect to stores

### Phase 4: Main Panel Implementation
- [ ] Input section with file drop zone
- [ ] Status section with progress
- [ ] Stats section with cards
- [ ] Reference list with expandable cards

### Phase 5: WebSocket Integration
- [ ] WebSocket hook
- [ ] Connect all real-time updates
- [ ] Implement cancel propagation

### Phase 6: Testing
- [ ] Playwright E2E test suite
- [ ] Vitest unit tests
- [ ] CI integration

### Phase 7: Polish
- [ ] Logging system
- [ ] Error boundaries
- [ ] Accessibility improvements
- [ ] Performance optimization

---

## Logging Strategy

### Frontend (Console)

```javascript
// utils/logger.js
const LOG_LEVELS = { DEBUG: 0, INFO: 1, WARN: 2, ERROR: 3 };

function log(level, component, message, data) {
  const timestamp = new Date().toISOString();
  console[level](`[${timestamp}] [${component}] ${message}`, data || '');
}
```

Log points:
- WebSocket connect/disconnect/messages
- API requests/responses
- State changes
- User interactions

### Backend (Structured)

Using Python's `logging` module with format:
```
[2026-01-08 10:30:45] [INFO] [refchecker] Starting check for arxiv:2401.12345
[2026-01-08 10:30:46] [INFO] [refchecker] Extracted 15 references
[2026-01-08 10:30:47] [DEBUG] [refchecker] Checking reference 1/15: Smith et al.
```

---

## File Size Configuration

```python
# backend/main.py
from fastapi import UploadFile
MAX_UPLOAD_SIZE = 200 * 1024 * 1024  # 200MB

@app.post("/api/check")
async def start_check(file: UploadFile = None):
    if file and file.size > MAX_UPLOAD_SIZE:
        raise HTTPException(413, "File exceeds 200MB limit")
```

---

## Notes

- History is global (no user auth) - can add later for hosted deployment
- API keys are encrypted server-side with AES-256
- vLLM is the only provider that doesn't require an API key
- Azure requires both API key AND endpoint URL
