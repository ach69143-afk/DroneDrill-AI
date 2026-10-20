#!/usr/bin/env bash
# DroneDrill AI - Linux / macOS Single-Command Launcher
set -e
echo "[DroneDrill AI] Starting server at http://127.0.0.1:8000 ..."
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
