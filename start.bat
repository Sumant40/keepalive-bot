@echo off
title KeepAlive Bot
color 0A
echo.
echo  ================================================
echo    KeepAlive Bot - Starting up...
echo  ================================================
echo.

cd /d "%~dp0"

echo [1/3] Installing Python dependencies...
pip install -r requirements.txt --quiet

echo [2/3] Installing Playwright Chromium browser...
python -m playwright install chromium

echo [3/3] Launching app...
echo.
echo  Dashboard will open at: http://localhost:5000
echo  Press Ctrl+C to stop.
echo.

start "" http://localhost:5000
python app.py

pause
