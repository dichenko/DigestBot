@echo off
chcp 65001 >nul
echo ============================================
echo   Telegram Digest Bot — Setup Session
echo ============================================
echo.

if not exist ".venv\" (
    echo [1/3] Creating virtual environment...
    python -m venv .venv
)

echo [2/3] Installing dependencies...
.venv\Scripts\python.exe -m pip install -q -r requirements.txt

echo [3/3] Running session setup...
echo.
.venv\Scripts\python.exe setup_session.py

echo.
echo Done! Session file created.
pause
