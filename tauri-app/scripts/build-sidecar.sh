#!/usr/bin/env bash
# Build the PyInstaller sidecar and place it under src-tauri/binaries/
# with the Rust target-triple suffix that Tauri's externalBin expects.
#
# Usage:
#   ./scripts/build-sidecar.sh
#
# Env overrides:
#   PYTHON      - Python interpreter to use (default: python3)
#   TARGET      - Force a specific Rust target triple
#   SKIP_WEB    - "1" to skip rebuilding the React frontend
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TAURI_APP_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
REPO_ROOT="$( cd "$TAURI_APP_DIR/.." && pwd )"

PYTHON="${PYTHON:-python3}"

detect_target() {
  if [[ -n "${TARGET:-}" ]]; then
    echo "$TARGET"
    return
  fi
  local host
  host="$(rustc -vV 2>/dev/null | sed -n 's/^host: //p')"
  if [[ -n "$host" ]]; then
    echo "$host"
    return
  fi
  # Fallback when rustc isn't installed (CI image without Rust yet).
  local os arch
  os="$(uname -s)"; arch="$(uname -m)"
  case "$os/$arch" in
    Darwin/arm64)   echo "aarch64-apple-darwin" ;;
    Darwin/x86_64)  echo "x86_64-apple-darwin" ;;
    Linux/x86_64)   echo "x86_64-unknown-linux-gnu" ;;
    Linux/aarch64)  echo "aarch64-unknown-linux-gnu" ;;
    *) echo "Cannot detect target triple for $os/$arch" >&2; exit 1 ;;
  esac
}

TARGET_TRIPLE="$(detect_target)"
echo "▶ Building sidecar for target: $TARGET_TRIPLE"

# 1. Build the web UI into backend/static/ (skip with SKIP_WEB=1)
if [[ "${SKIP_WEB:-0}" != "1" ]]; then
  echo "▶ Building React frontend (web-ui)…"
  pushd "$REPO_ROOT/web-ui" >/dev/null
  if [[ ! -d node_modules ]]; then
    npm ci
  fi
  npm run build
  popd >/dev/null

  echo "▶ Copying dist into backend/static/"
  mkdir -p "$REPO_ROOT/backend/static"
  rm -rf "$REPO_ROOT/backend/static/assets"
  cp -R "$REPO_ROOT/web-ui/dist/." "$REPO_ROOT/backend/static/"
fi

# 2. Install Python build deps + project deps into the current env.
echo "▶ Installing PyInstaller and project deps…"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install pyinstaller
# Install the project itself (editable so PyInstaller can resolve backend.*, refchecker.*)
"$PYTHON" -m pip install -e "$REPO_ROOT[webui,llm]"

# 3. Run PyInstaller from the repo root so relative paths in the spec resolve.
echo "▶ Running PyInstaller…"
pushd "$REPO_ROOT" >/dev/null
REFCHECKER_REPO_ROOT="$REPO_ROOT" "$PYTHON" -m PyInstaller \
  --noconfirm --clean \
  --distpath "$TAURI_APP_DIR/python/dist" \
  --workpath "$TAURI_APP_DIR/python/build" \
  "$TAURI_APP_DIR/python/refchecker-server.spec"
popd >/dev/null

# 4. Copy + rename to the target-triple-suffixed name Tauri wants.
mkdir -p "$TAURI_APP_DIR/src-tauri/binaries"
SRC="$TAURI_APP_DIR/python/dist/refchecker-server"
EXT=""
if [[ "$TARGET_TRIPLE" == *windows* ]]; then
  SRC="${SRC}.exe"
  EXT=".exe"
fi
DEST="$TAURI_APP_DIR/src-tauri/binaries/refchecker-server-${TARGET_TRIPLE}${EXT}"
cp "$SRC" "$DEST"
chmod +x "$DEST" || true

echo "✅ Sidecar built: $DEST"
