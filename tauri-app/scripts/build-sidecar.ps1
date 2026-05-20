# Build the PyInstaller sidecar for Windows and place it under
# src-tauri/binaries/ with the Rust target-triple suffix Tauri expects.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1
#
# Env:
#   $env:PYTHON  - Python interpreter (default: python)
#   $env:TARGET  - Force a specific Rust target triple
#   $env:SKIP_WEB = "1" to skip the npm build

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$TauriDir    = (Resolve-Path "$ScriptDir\..").Path
$RepoRoot    = (Resolve-Path "$TauriDir\..").Path
$Python      = if ($env:PYTHON) { $env:PYTHON } else { "python" }

function Detect-Target {
  if ($env:TARGET) { return $env:TARGET }
  try {
    $line = (& rustc -vV 2>$null) | Where-Object { $_ -like "host: *" }
    if ($line) { return $line.Substring(6).Trim() }
  } catch {}
  return "x86_64-pc-windows-msvc"
}

$Target = Detect-Target
Write-Host "▶ Building sidecar for target: $Target"

if ($env:SKIP_WEB -ne "1") {
  Write-Host "▶ Building React frontend (web-ui)..."
  Push-Location "$RepoRoot\web-ui"
  if (-not (Test-Path "node_modules")) { npm ci }
  npm run build
  Pop-Location

  $StaticDir = "$RepoRoot\backend\static"
  New-Item -ItemType Directory -Force -Path $StaticDir | Out-Null
  if (Test-Path "$StaticDir\assets") { Remove-Item -Recurse -Force "$StaticDir\assets" }
  Copy-Item -Recurse -Force "$RepoRoot\web-ui\dist\*" $StaticDir
}

Write-Host "▶ Installing PyInstaller and project deps..."
& $Python -m pip install --upgrade pip
& $Python -m pip install pyinstaller
& $Python -m pip install -e "$RepoRoot[webui,llm]"

Write-Host "▶ Running PyInstaller..."
Push-Location $RepoRoot
$env:REFCHECKER_REPO_ROOT = $RepoRoot
& $Python -m PyInstaller `
  --noconfirm --clean `
  --distpath "$TauriDir\python\dist" `
  --workpath "$TauriDir\python\build" `
  "$TauriDir\python\refchecker-server.spec"
Pop-Location

New-Item -ItemType Directory -Force -Path "$TauriDir\src-tauri\binaries" | Out-Null
$Src  = "$TauriDir\python\dist\refchecker-server.exe"
$Dest = "$TauriDir\src-tauri\binaries\refchecker-server-$Target.exe"
Copy-Item -Force $Src $Dest
Write-Host "✅ Sidecar built: $Dest"
