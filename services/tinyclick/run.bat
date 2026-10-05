@echo off
rem Starts the TinyClick grounding server on the Intel Arc GPU (http://127.0.0.1:8765).
rem It runs in its own environment (.venv-xpu in the project folder); see services/tinyclick/README.md.
rem Press Ctrl+C in this window to stop it.
cd /d "%~dp0..\.."
set HF_HOME=%CD%\models\hf
".venv-xpu\Scripts\python.exe" -u services\tinyclick\server.py
pause
