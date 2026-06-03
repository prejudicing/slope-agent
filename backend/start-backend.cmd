@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
