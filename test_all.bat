@echo off
REM Test script for RefChecker package installation
REM This script installs the package, runs tests, and runs Playwright E2E tests

echo ============================================
echo RefChecker Package Installation and Test
echo ============================================
echo.

REM Check for virtual environment
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
    set PIP=.venv\Scripts\pip.exe
) else (
    set PYTHON=python
    set PIP=pip
)

echo Using Python: %PYTHON%
echo.

REM Install package in editable mode with all dependencies
echo [1/4] Installing package with webui and llm dependencies...
%PIP% install -e ".[webui,llm]" --quiet
if errorlevel 1 (
    echo ERROR: Package installation failed
    exit /b 1
)
echo Package installed successfully.
echo.

REM Run the package installation test
echo [2/4] Running package installation tests...
%PYTHON% test_package_install.py
if errorlevel 1 (
    echo WARNING: Some package tests failed
)
echo.

REM Test CLI
echo [3/4] Testing CLI...
academic-refchecker --help > nul 2>&1
if errorlevel 1 (
    echo ERROR: academic-refchecker CLI not accessible
) else (
    echo academic-refchecker CLI: OK
)

refchecker-webui --help > nul 2>&1
if errorlevel 1 (
    echo ERROR: refchecker-webui CLI not accessible
) else (
    echo refchecker-webui CLI: OK
)
echo.

REM Run Playwright tests if requested
if "%1"=="--e2e" (
    echo [4/4] Running Playwright E2E tests...
    cd web-ui
    call npm install --quiet
    call npx playwright install chromium --quiet
    call npm run test:e2e -- --project=chromium
    cd ..
) else (
    echo [4/4] Skipping E2E tests (use --e2e flag to run them)
)

echo.
echo ============================================
echo Test complete!
echo ============================================
