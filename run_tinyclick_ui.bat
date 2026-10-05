@echo off
rem Starts the TinyClick tester on the Intel Arc GPU, then open http://127.0.0.1:8765 in your browser.
rem Everything it uses lives inside this folder. Press Ctrl+C in this window to stop it.
cd /d "%~dp0"
set HF_HOME=%~dp0models\hf
".venv-xpu\Scripts\python.exe" -u tinyclick_ui.py
pause
