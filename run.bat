@echo off
REM DroneDrill AI - Windows Single-Command Launcher
echo [DroneDrill AI] Starting server at http://127.0.0.1:8000 ...
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
