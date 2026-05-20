#!/usr/bin/env bash
# Regenerate the src-tauri/icons/* set from web-ui/public/favicon.svg.
# Run once locally and commit the results — CI doesn't need to rerun.
#
# Requires: rsvg-convert OR magick (ImageMagick) AND `npx @tauri-apps/cli`.
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TAURI_APP_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
REPO_ROOT="$( cd "$TAURI_APP_DIR/.." && pwd )"

SRC_SVG="$REPO_ROOT/web-ui/public/favicon.svg"
OUT_PNG="$TAURI_APP_DIR/src-tauri/icons/app-icon.png"
mkdir -p "$TAURI_APP_DIR/src-tauri/icons"

echo "▶ Rendering 1024x1024 source PNG from $SRC_SVG"
if command -v rsvg-convert >/dev/null 2>&1; then
  rsvg-convert -w 1024 -h 1024 "$SRC_SVG" -o "$OUT_PNG"
elif command -v magick >/dev/null 2>&1; then
  magick -background none -resize 1024x1024 "$SRC_SVG" "$OUT_PNG"
elif command -v convert >/dev/null 2>&1; then
  convert -background none -resize 1024x1024 "$SRC_SVG" "$OUT_PNG"
else
  echo "Install rsvg-convert (librsvg) or ImageMagick first." >&2
  exit 1
fi

echo "▶ Running tauri icon to fan out all platform sizes"
cd "$TAURI_APP_DIR"
npx --yes @tauri-apps/cli icon "$OUT_PNG" --output src-tauri/icons

echo "✅ Icons regenerated in src-tauri/icons/"
