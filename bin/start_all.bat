@echo off
chcp 65001 >nul 2>&1
title TradingView → MT5 Bridge

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║      TradingView → MT5 Bridge — Startup         ║
echo ╚══════════════════════════════════════════════════╝
echo.

set "ROOT=%~dp0.."
set "DOCKER_DIR=%ROOT%\docker"
set "SCRIPTS_DIR=%ROOT%\scripts"

:: ── Check docker/.env ───────────────────────────────────────────
if not exist "%DOCKER_DIR%\.env" (
    echo [ERROR] Missing file: docker\.env
    echo.
    echo Steps:
    echo   1. Copy docker\.env.example  →  docker\.env
    echo   2. Go to https://dashboard.ngrok.com/get-started/your-authtoken
    echo   3. Paste your token into docker\.env
    echo.
    pause
    exit /b 1
)

:: ── Check MT5 Executor (port 5001) ──────────────────────────────
netstat -ano | findstr ":5001 " >nul 2>&1
if errorlevel 1 (
    echo [INFO] Starting MT5 Executor...
    start "MT5 Executor" /min python "%SCRIPTS_DIR%\mt5_executor.py"
    timeout /t 4 /nobreak >nul
    netstat -ano | findstr ":5001 " >nul 2>&1
    if errorlevel 1 (
        echo [WARN] MT5 Executor failed to start — make sure MetaTrader 5 is open and logged in
    ) else (
        echo [OK]   MT5 Executor started ^(port 5001^)
    )
) else (
    echo [OK]   MT5 Executor already running ^(port 5001^)
)

:: ── Start Docker Compose ────────────────────────────────────────
echo.
echo [INFO] Starting Docker (tv-webhook + ngrok)...
cd /d "%DOCKER_DIR%"
docker-compose up -d 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Docker Compose failed.
    echo Make sure Docker Desktop is running.
    pause
    exit /b 1
)

:: ── Wait for ngrok ──────────────────────────────────────────────
echo.
echo [INFO] Waiting for ngrok...
set "NGROK_URL="
set /a RETRY=0
:wait_loop
timeout /t 3 /nobreak >nul
set /a RETRY+=1
for /f "delims=" %%u in ('python -c "import urllib.request,json; d=json.loads(urllib.request.urlopen(\"http://localhost:4040/api/tunnels\").read()); t=[x[\"public_url\"] for x in d[\"tunnels\"] if x[\"public_url\"].startswith(\"https\")]; print(t[0] if t else \"\")" 2^>nul') do set "NGROK_URL=%%u"
if "%NGROK_URL%"=="" (
    if %RETRY% LSS 10 goto wait_loop
    echo [WARN] ngrok not responding. Check: http://localhost:4040
    goto show_status
)

:: ── Show URL ────────────────────────────────────────────────────
echo.
echo ╔══════════════════════════════════════════════════╗
echo ║  WEBHOOK URL — PASTE INTO TRADINGVIEW:          ║
echo ║                                                  ║
echo    %NGROK_URL%/webhook
echo ║                                                  ║
echo ║  TradingView → Alert → Notifications            ║
echo ║  → Webhook URL → paste the URL above            ║
echo ╚══════════════════════════════════════════════════╝

:show_status
echo.
echo ─────────────────────────────────────────────────
echo   Active services:
echo     Webhook server : http://localhost:5000
echo     MT5 Executor   : http://localhost:5001
echo     ngrok dashboard: http://localhost:4040
echo ─────────────────────────────────────────────────
echo.
echo Open ngrok dashboard in browser? (Y/N)
set /p OPEN=
if /i "%OPEN%"=="Y" start http://localhost:4040
echo.
echo [OK] All systems running. Keep this window open.
echo      Press Ctrl+C to stop, or run stop_all.bat
echo.
pause
