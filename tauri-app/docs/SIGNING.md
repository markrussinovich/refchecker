# Signing & Notarization

The `desktop-release.yml` workflow builds the Tauri desktop app for macOS (Apple Silicon + Intel), Windows, and Linux. macOS signing and notarization are wired in but **only run when the relevant secrets exist** — forks and unsigned local builds still work, they just produce unsigned `.app`/`.dmg`/`.msi` artifacts.

## macOS — what you need from Apple

You need an active **Apple Developer Program** membership ($99/yr).

| Asset | Where to get it |
|---|---|
| Developer ID Application certificate (`.p12`) | Apple Developer → Certificates → "+" → **Developer ID Application** → upload a CSR from Keychain Access, download the `.cer`, import to Keychain, then **right-click → Export → .p12** with a password. |
| App-specific password | <https://appleid.apple.com> → Sign-in & Security → App-Specific Passwords → "+". Label it e.g. `refchecker-notarize`. **This is not your Apple ID password.** |
| Team ID | <https://developer.apple.com/account> → Membership details → 10-character string. |

### Exporting the cert to base64 (paste into GitHub secrets)

```bash
base64 -i DeveloperIDApplication.p12 | pbcopy   # macOS — now on your clipboard
# or
base64 -i DeveloperIDApplication.p12 -o cert.p12.base64
```

### Finding your signing identity string

After importing the `.p12` into Keychain Access, run:

```bash
security find-identity -v -p codesigning
```

Use the full quoted string, e.g. `Developer ID Application: Your Name (ABCD123456)`.

## GitHub Actions secrets

Add these in **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Required | Value |
|---|---|---|
| `APPLE_CERTIFICATE` | macOS signing | base64-encoded `.p12` from above |
| `APPLE_CERTIFICATE_PASSWORD` | macOS signing | password you set when exporting the `.p12` |
| `APPLE_SIGNING_IDENTITY` | macOS signing | full identity string, e.g. `Developer ID Application: Your Name (ABCD123456)` |
| `APPLE_ID` | macOS notarization | your Apple ID email |
| `APPLE_PASSWORD` | macOS notarization | app-specific password (not your AppleID password) |
| `APPLE_TEAM_ID` | macOS notarization | 10-char team ID |
| `KEYCHAIN_PASSWORD` | macOS signing | any random string — used only inside the GitHub runner |

If all macOS secrets are missing, the workflow falls back to an unsigned macOS build (still useful for testing, but Gatekeeper will block first-launch without right-click → Open).

## After a fork

The included workflow keeps working unchanged for anyone who forks the repo — they just add **their own** secrets in their fork's Settings, and the workflow signs with their cert. **No code changes are required after a PR is merged**: every fork/clone uses its own secrets via the same workflow.

If you'd rather strip signing from a fork, delete the `Import Apple signing certificate`, `Pre-sign PyInstaller sidecar (macOS)`, and the `APPLE_*` env entries from `Build Tauri bundle`.

## Windows

Windows code signing is not enabled by default (no `signtool` step is run). If you have a Windows EV cert and want to add signing, edit `desktop-release.yml`:

```yaml
- name: Sign Windows binaries
  if: matrix.platform.os == 'windows-latest' && env.WINDOWS_CERTIFICATE != ''
  env:
    WINDOWS_CERTIFICATE: ${{ secrets.WINDOWS_CERTIFICATE }}
    WINDOWS_CERTIFICATE_PASSWORD: ${{ secrets.WINDOWS_CERTIFICATE_PASSWORD }}
  shell: pwsh
  run: |
    $cert = "$env:RUNNER_TEMP\cert.pfx"
    [IO.File]::WriteAllBytes($cert, [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE))
    & "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe" `
      sign /f $cert /p $env:WINDOWS_CERTIFICATE_PASSWORD /tr http://timestamp.digicert.com /td sha256 /fd sha256 `
      tauri-app/src-tauri/target/${{ matrix.platform.rust_target }}/release/bundle/msi/*.msi
```

## Linux

Linux bundles (`.deb`, `.AppImage`) aren't signed — that's normal. AppImage users can verify integrity via SHA256 sums, which `softprops/action-gh-release` includes automatically when you attach the file.

## Local signing (without CI)

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (ABCD123456)"
export APPLE_ID="you@example.com"
export APPLE_PASSWORD="app-specific-password"
export APPLE_TEAM_ID="ABCD123456"

cd tauri-app
./scripts/build-sidecar.sh
npm ci
npx tauri build --target aarch64-apple-darwin
```

Tauri picks up those env vars and signs + notarizes the bundle automatically.

## Triggering a release build

Either:

1. **Tag push**: `git tag desktop-v0.1.0 && git push origin desktop-v0.1.0` — produces a draft GitHub Release with all platform artifacts attached.
2. **Manual run**: GitHub → Actions → Desktop release → Run workflow.
3. **PR**: any PR touching `tauri-app/**` automatically builds (but does not release).
