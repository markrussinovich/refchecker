#!/usr/bin/env bash
# Generate a Tauri updater signing keypair.
#
# Usage:
#   ./scripts/generate-updater-key.sh [--password] [-o OUTPUT]
#
# Produces:
#   OUTPUT       (private key — DO NOT COMMIT, paste into the
#                 TAURI_SIGNING_PRIVATE_KEY GitHub secret)
#   OUTPUT.pub   (public key — copy the single-line content into
#                 tauri.conf.json → plugins.updater.pubkey)
#
# Lose either and you can never sign updates for this app again, so back
# them up to a password manager.
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TAURI_APP_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

OUTPUT="${TAURI_APP_DIR}/refchecker-updater.key"
PASSWORD=""
PROMPT_PASSWORD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --password) PROMPT_PASSWORD=1; shift ;;
    -o|--output) OUTPUT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

if [[ "$PROMPT_PASSWORD" == "1" ]]; then
  read -rsp "Updater key password (recommended): " PASSWORD
  echo
fi

CI=true npx --yes @tauri-apps/cli@2 signer generate \
  -p "$PASSWORD" \
  -w "$OUTPUT" \
  --force

echo
echo "✅ Keypair generated."
echo
echo "Public key (copy into tauri-app/src-tauri/tauri.conf.json → plugins.updater.pubkey):"
echo "---"
cat "${OUTPUT}.pub"
echo "---"
echo
echo "Private key file: $OUTPUT"
echo "Paste its full contents into the GitHub secret TAURI_SIGNING_PRIVATE_KEY."
if [[ -n "$PASSWORD" ]]; then
  echo "Also set TAURI_SIGNING_PRIVATE_KEY_PASSWORD to the password you typed."
fi
echo
echo "⚠️  Add ${OUTPUT##*/} to .gitignore (already covered by tauri-app/.gitignore)."
