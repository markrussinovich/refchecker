# Signing, Notarization & Auto-Updates

The `desktop-release.yml` workflow builds the Tauri desktop app for macOS (Apple Silicon + Intel), Windows, and Linux. It additionally **code-signs and notarizes** the macOS bundle, **signs Tauri updater artifacts** with an Ed25519 key, and assembles a `latest.json` manifest so the in-app auto-updater works.

All three signing paths are gated on the relevant secret being present, so:
- Forks without your secrets still produce unsigned builds.
- Adding your secrets to a fork's settings is enough — no code changes needed.

## Secret list (TL;DR)

| Secret | Purpose | Required for |
|---|---|---|
| `APPLE_CERTIFICATE` | base64 of Developer ID Application `.p12` | macOS code signing |
| `APPLE_CERTIFICATE_PASSWORD` | password for the `.p12` | macOS code signing |
| `APPLE_SIGNING_IDENTITY` | full identity string, e.g. `Developer ID Application: Your Name (ABCD123456)` | macOS code signing |
| `APPLE_ID` | Apple ID email | macOS notarization |
| `APPLE_PASSWORD` | app-specific password | macOS notarization |
| `APPLE_TEAM_ID` | 10-char team ID | macOS notarization |
| `KEYCHAIN_PASSWORD` | any random string | macOS keychain on the runner |
| **`TAURI_SIGNING_PRIVATE_KEY`** | **full contents of the updater private-key file** | **Auto-update signature** |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | password for the updater key (if you set one) | Auto-update signature |
| *(optional)* `WINDOWS_CERTIFICATE` / `WINDOWS_CERTIFICATE_PASSWORD` | base64 EV cert + password | Windows code signing |

## macOS — getting the Apple bits

Active **Apple Developer Program** membership ($99/yr).

| Asset | Where to get it |
|---|---|
| Developer ID Application cert (`.p12`) | Apple Developer → Certificates → "+" → **Developer ID Application** → upload a CSR from Keychain Access, download `.cer`, import to Keychain, **right-click → Export → .p12** with a password. |
| App-specific password | <https://appleid.apple.com> → Sign-in & Security → App-Specific Passwords → "+". Label it `refchecker-notarize`. **Not your Apple ID password.** |
| Team ID | <https://developer.apple.com/account> → Membership details → 10-char string. |

Export the cert to base64 for the GitHub secret:

```bash
base64 -i DeveloperIDApplication.p12 | pbcopy        # macOS — clipboard
# or
base64 -i DeveloperIDApplication.p12 -o cert.p12.base64
```

Find your signing identity string:

```bash
security find-identity -v -p codesigning
# → "Developer ID Application: Your Name (ABCD123456)"
```

## Auto-update signing key

The Tauri updater requires its own Ed25519 keypair. **This is separate from your Apple Developer cert** — it signs the update payload itself, so the running app can verify a downloaded `.app.tar.gz` came from you and not a tampered mirror.

Generate the keypair once (locally) and stash both halves:

```bash
cd tauri-app
./scripts/generate-updater-key.sh --password    # prompts you for a passphrase
# or, no-password:
./scripts/generate-updater-key.sh
```

The script writes:

- `tauri-app/refchecker-updater.key` — **private key**. Gitignored. Paste full contents into the `TAURI_SIGNING_PRIVATE_KEY` GitHub secret. If you set a passphrase, also set `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.
- `tauri-app/refchecker-updater.key.pub` — public key. Copy the single-line content into `tauri-app/src-tauri/tauri.conf.json` → `plugins.updater.pubkey` and commit it.

⚠️ **If you lose the private key, you can never sign updates for this app again.** Existing installs would refuse update payloads signed with a new key. Back the file up to a password manager.

The repo currently ships with a pre-generated public key. If you keep that public key, you must use the matching private key. If you rotate keys after merging, every existing user has to manually install the next version (they won't get it via auto-update).

## How auto-updates flow on a release

1. You push a `desktop-v0.1.0` tag.
2. The workflow:
   - Extracts `0.1.0` from the tag and updates `tauri-app/package.json` `version`. Tauri reads `version` from `package.json` (see `tauri.conf.json` `"version": "../package.json"`), so the bundled app and the embedded updater both use `0.1.0` end-to-end.
   - Builds each platform with `createUpdaterArtifacts: true`, producing `.app.tar.gz` / `.msi.zip` / `.AppImage.tar.gz` plus a `.sig` next to each.
   - Assembles a single `latest.json` referencing those artifacts at their final release-asset URLs, with the platform-keyed signatures.
   - Creates a draft GitHub Release containing every artifact **plus** `latest.json`.
3. You review the draft and publish it.
4. Installed apps poll `https://github.com/markrussinovich/refchecker/releases/latest/download/latest.json` on startup. GitHub redirects that URL to whatever the current latest release exposes, so the endpoint is fully dynamic — you never have to touch the URL in `tauri.conf.json`.
5. If `latest.json`'s `version` is higher than the running app's, the updater downloads the platform-appropriate bundle, verifies the signature against the embedded public key, applies the update, and restarts.

## After a fork

The workflow file is generic — it reads from `secrets.APPLE_*` / `secrets.TAURI_SIGNING_PRIVATE_KEY` of whichever fork runs it. After this PR merges:
- Your repo continues to sign with your secrets.
- Anyone who forks adds their own secrets, gets signed builds with their cert + keypair.
- **The shipped public key in `tauri.conf.json` belongs to the original repo owner.** If a fork wants its own auto-update channel, it should run `./scripts/generate-updater-key.sh`, replace `plugins.updater.pubkey` in `tauri.conf.json`, change `plugins.updater.endpoints[0]` to its own GitHub releases URL, and put its private key into its own `TAURI_SIGNING_PRIVATE_KEY` secret.

## Windows signing (optional)

Not enabled by default. To add it, drop this step into `desktop-release.yml` before "Collect artifacts":

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
      sign /f $cert /p $env:WINDOWS_CERTIFICATE_PASSWORD `
      /tr http://timestamp.digicert.com /td sha256 /fd sha256 `
      tauri-app/src-tauri/target/${{ matrix.platform.rust_target }}/release/bundle/msi/*.msi
```

## Linux

Linux bundles (`.deb`, `.AppImage`) aren't code-signed — that's normal. The updater Ed25519 signature still protects integrity end-to-end.

## Local signing

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (ABCD123456)"
export APPLE_ID="you@example.com"
export APPLE_PASSWORD="app-specific-password"
export APPLE_TEAM_ID="ABCD123456"
export TAURI_SIGNING_PRIVATE_KEY="$(cat tauri-app/refchecker-updater.key)"
# export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="..."     # if you set one

cd tauri-app
./scripts/build-sidecar.sh
npm ci
npx tauri build --target aarch64-apple-darwin
```

## Triggering a release build

| How | What happens |
|---|---|
| `git tag desktop-v0.2.0 && git push origin desktop-v0.2.0` | Full build + signed updater manifest + draft Release |
| Actions → Desktop release → Run workflow | Same as above, lets you override the version |
| PR touching `tauri-app/**` | Build-only validation (no release published) |

## Verifying a signed macOS build locally

```bash
codesign --verify --deep --strict --verbose=2 /Applications/RefChecker.app
spctl --assess -vv /Applications/RefChecker.app                # → "accepted"
```

## Verifying an updater signature locally

```bash
# After downloading RefChecker_0.1.0_aarch64.app.tar.gz and .sig from a release:
npx --yes @tauri-apps/cli@2 signer sign \
  --verify \
  -k tauri-app/refchecker-updater.key.pub \
  -s RefChecker_0.1.0_aarch64.app.tar.gz.sig \
  RefChecker_0.1.0_aarch64.app.tar.gz
```
