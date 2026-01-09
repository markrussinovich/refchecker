# RefChecker Web UI - Quick Start

## ⚡ Fast Start (Windows)

### Option 1: One-Click Startup
```cmd
start_webui.bat
```

### Option 2: Manual Startup

**Terminal 1 - Backend:**
```cmd
cd backend
..\.venv\Scripts\python.exe main.py
```

**Terminal 2 - Frontend:**
```cmd
cd web-ui
npm run dev
```

Then open: **http://localhost:5173**

---

## 🧪 Testing

```cmd
cd web-ui
npx playwright test
```

---

## 📝 Environment Setup

Make sure `ANTHROPIC_API_KEY` is set:

```cmd
set ANTHROPIC_API_KEY=your_api_key_here
```

---

## ✅ Verify Backend is Running

```cmd
curl http://localhost:8000/api/health
```

Should return: `{"status":"healthy"}`

---

## 📚 Try It Out

1. Open **http://localhost:5173**
2. Enter ArXiv ID: **1706.03762**
3. Click "Check References"
4. Watch real-time validation!

---

## 📖 Full Documentation

- **README_WEBUI.md** - Complete user guide
- **WEBUI_IMPLEMENTATION.md** - Technical details
- **WEBUI_COMPLETE.md** - Project summary

---

## 🐛 Troubleshooting

**Backend won't start?**
- Check ANTHROPIC_API_KEY is set
- Make sure .venv is activated
- Verify Python 3.7+ is installed

**Frontend won't start?**
- Run `npm install` in web-ui directory
- Check Node.js version: `node --version` (need 18+)

**Can't connect?**
- Ensure backend shows: "Uvicorn running on http://0.0.0.0:8000"
- Check firewall isn't blocking ports 5173 or 8000
