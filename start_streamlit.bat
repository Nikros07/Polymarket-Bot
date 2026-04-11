@echo off
setlocal
title AI Decision System

:: Activate venv if present
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [WARN] No .venv found. Using system Python.
)

:: Load .env variables into environment
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" (
            set "%%A=%%B"
        )
    )
)

echo.
echo  Starting AI Decision System...
echo  URL: http://localhost:8501
echo  Press Ctrl+C to stop.
echo.

streamlit run streamlit_app.py --server.port 8501 --server.headless false --browser.gatherUsageStats false

pause
