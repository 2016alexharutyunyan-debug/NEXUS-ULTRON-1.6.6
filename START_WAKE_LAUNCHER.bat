@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ULTRON Wake Launcher

if exist "payload\.venv\Scripts\python.exe" (
  set "PY=payload\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" "payload\jarvis_wake_launcher.py"
pause
