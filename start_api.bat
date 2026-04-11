@echo off
setlocal
title AI Decision System — API Server

if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

echo.
echo  Starting FastAPI backend...
echo  URL:  http://localhost:8000
echo  Docs: http://localhost:8000/docs
echo.

uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

pause
