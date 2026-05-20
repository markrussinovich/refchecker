# RefChecker Desktop (Tauri)

A native desktop wrapper around the [RefChecker](https://github.com/ArioMoniri/refchecker) web UI for macOS, Windows, and Linux. Built with [Tauri 2.x](https://tauri.app).

The Python FastAPI backend is bundled as a [PyInstaller](https://pyinstaller.org/) sidecar binary so end users don't need Python installed. The Tauri shell spawns the sidecar on an OS-assigned port, waits for `/api/health`, and loads the served SPA in the app window.

## Layout

```
tauri-app/
├── src-tauri/            # Rust crate (Tauri 2.x)
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   ├── build.rs
│   ├── capabilities/default.json
│   ├── icons/            # App icons (filled in by `tauri icon`)
│   ├── binaries/         # PyInstaller output lands here (gitignored)
│   └── src/main.rs       # Sidecar lifecycle + window navigation
├── frontend/             # Tiny placeholder loaded before sidecar is up
├── python/
│   ├── server_entry.py   # Sidecar entrypoint (imports backend.main:app)
│   └── refchecker-server.spec  # PyInstaller spec
├── scripts/
│   ├── build-sidecar.sh
│   └── build-sidecar.ps1
└── docs/SIGNING.md
```

## Local development

Requires: Node 20+, Rust (stable), Python 3.11+, and the repo's Python deps installed (`pip install -e ..[webui,llm]` from the repo root).

```bash
# 1. From repo root, build the React web UI into backend/static/ (if not already built)
cd ../web-ui && npm ci && npm run build && cp -R dist/* ../backend/static/

# 2. Build the PyInstaller sidecar
cd ../tauri-app
./scripts/build-sidecar.sh         # macOS/Linux
# scripts\build-sidecar.ps1        # Windows

# 3. Install JS deps and run Tauri in dev mode
npm ci
npm run tauri dev
```

## Production build

```bash
npm run tauri build
```

Outputs:

- macOS: `src-tauri/target/release/bundle/dmg/RefChecker_*.dmg` and `.app`
- Windows: `src-tauri/target/release/bundle/msi/RefChecker_*.msi`
- Linux: `src-tauri/target/release/bundle/{deb,appimage}/`

## Signing & notarization

See [`docs/SIGNING.md`](docs/SIGNING.md) for the full secret list and CI configuration. The included GitHub Actions workflow (`.github/workflows/desktop-release.yml`) builds and signs for all three platforms on release tags.
