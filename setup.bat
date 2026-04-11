@echo off
setlocal
title AI Decision System — Setup

echo.
echo  ============================================
echo   AI Decision System — Windows Setup
echo  ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found.
    echo  Please install Python 3.10+ from https://python.org
    echo  Make sure "Add Python to PATH" is checked!
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo  Python %%v found

:: Create venv
if not exist ".venv" (
    echo.
    echo  Creating virtual environment...
    python -m venv .venv
    echo  Done.
)

:: Activate + install
echo.
echo  Installing dependencies (this takes 1-3 minutes)...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  [ERROR] Dependency install failed. Check your internet connection.
    pause
    exit /b 1
)
echo  Dependencies installed.

:: Create .env from template
if not exist ".env" (
    echo.
    echo  Creating .env config file...
    copy .env.example .env >nul
    echo  IMPORTANT: Open .env and add your ANTHROPIC_API_KEY
    echo  Or set DEMO_MODE=true to test without an API key.
)

:: Create data dir
if not exist "backend\data" mkdir backend\data

echo.
echo  ============================================
echo   Setup complete!
echo  ============================================
echo.
echo  Next steps:
echo    1. Open .env and set ANTHROPIC_API_KEY
echo       (or DEMO_MODE=true for testing)
echo.
echo    2. Run:  start_streamlit.bat
echo       Opens: http://localhost:8501
echo.
pause
