@echo off
chcp 65001 >nul 2>&1
title Webhook URL

echo.
echo Fetching ngrok URL...
echo.

for /f "delims=" %%u in ('python -c "import urllib.request,json; d=json.loads(urllib.request.urlopen(\"http://localhost:4040/api/tunnels\").read()); t=[x[\"public_url\"] for x in d[\"tunnels\"] if x[\"public_url\"].startswith(\"https\")]; print(t[0] if t else \"UNAVAILABLE\")" 2^>nul') do set "NGROK_URL=%%u"

if "%NGROK_URL%"=="" set "NGROK_URL=UNAVAILABLE (run start_all.bat first)"

echo ══════════════════════════════════════════════════
echo   WEBHOOK URL:
echo   %NGROK_URL%/webhook
echo ══════════════════════════════════════════════════
echo.
echo   Paste into TradingView:
echo   Alert → Notifications → Webhook URL
echo.

python -c "import urllib.request,json; d=json.loads(urllib.request.urlopen(\"http://localhost:5001/status\").read()); print(\"MT5: CONNECTED\" if d.get(\"mt5_connected\") else \"MT5: NOT CONNECTED\"); print(\"Open positions:\", len(d.get(\"positions\",[])) )" 2>nul

echo.
pause
