@echo off
echo ===============================================
echo RefChecker Web UI - Startup Script
echo ===============================================
echo.

REM Check if ANTHROPIC_API_KEY is set
if "%ANTHROPIC_API_KEY%"=="" (
    echo ERROR: ANTHROPIC_API_KEY environment variable is not set!
    echo.
    echo Please set it first:
    echo   set ANTHROPIC_API_KEY=your_api_key_here
    echo.
    pause
    exit /b 1
)

echo Starting Backend Server...
echo.
start "RefChecker Backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

echo Waiting for backend to start...
timeout /t 5 /nobreak > nul

echo.
echo Starting Frontend Server...
echo.
start "RefChecker Frontend" cmd /k "cd web-ui && npm run dev"

echo.
echo ===============================================
echo Both servers starting...
echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo.
echo Open http://localhost:5173 in your browser
echo ===============================================
echo.
echo Press any key to stop both servers...
pause > nul

taskkill /FI "WindowTitle eq RefChecker Backend*" /T /F > nul 2>&1
taskkill /FI "WindowTitle eq RefChecker Frontend*" /T /F > nul 2>&1

echo.
echo Servers stopped.
pause
