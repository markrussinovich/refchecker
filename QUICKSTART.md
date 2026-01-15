# RefChecker Web UI - Quick Start

## ⚡ Option 1: Pip Install (Recommended)

The simplest way to run RefChecker Web UI:

```bash
# Install RefChecker with all features
pip install academic-refchecker[llm,webui]

# Start the web server
refchecker-webui
```

Then open **http://localhost:8000** in your browser.

**Optional environment variables:**
```bash
# Set API keys for LLM and faster verification
export ANTHROPIC_API_KEY=your_key_here          # or OPENAI_API_KEY
export SEMANTIC_SCHOLAR_API_KEY=your_key_here   # Optional, 5x faster
```

---

## 🛠️ Option 2: Run from Cloned Repository (Development)

For development or if you've cloned the repository:

### Windows
```cmd
cd web-ui
npm install
npm start
```

### macOS/Linux
```bash
cd web-ui
npm install
npm start
```

Then open **http://localhost:5173** in your browser.

### Alternative: Start Servers Separately

*Terminal 1 - Backend:*
```bash
python -m uvicorn backend.main:app --reload --port 8000
```

*Terminal 2 - Frontend:*
```bash
cd web-ui
npm run dev
```

---

## 🧪 Testing (Development Only)

```bash
cd web-ui
npx playwright test
```

---

## ✅ Verify Server is Running

```bash
curl http://localhost:8000/
```

Should return the web interface or API info.

---

## 📚 Try It Out

1. Open the web UI in your browser
2. Enter ArXiv ID: **1706.03762**
3. Click "Check References"
4. Watch real-time validation!

---

## 🐛 Troubleshooting

**Backend won't start?**
- Check that you have an LLM API key set (ANTHROPIC_API_KEY or OPENAI_API_KEY)
- Verify Python 3.8+ is installed

**Frontend won't start? (development mode)**
- Run `npm install` in web-ui directory
- Check Node.js version: `node --version` (need 18+)

**Can't connect?**
- Check firewall isn't blocking port 8000 (or 5173 for development mode)
- Verify the server is running
