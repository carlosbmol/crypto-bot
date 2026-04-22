@echo off
chcp 65001 >nul 2>&1
title Stop TradingView → MT5 Bridge

echo.
echo [INFO] Stopping Docker (tv-webhook + ngrok)...
cd /d "%~dp0..\docker"
docker-compose down

echo.
echo [INFO] Stopping MT5 Executor (port 5001)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5001 "') do (
    taskkill /PID %%p /F >nul 2>&1
)

echo.
echo [OK] All services stopped.
echo.
pause
