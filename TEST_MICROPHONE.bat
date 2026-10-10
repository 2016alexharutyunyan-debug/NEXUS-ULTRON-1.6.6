@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title JARVIS Microphone Test

if exist "payload\.venv\Scripts\python.exe" (
  set "PY=payload\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" "payload\voice_diagnostics.py"
echo.
echo If the signal is too quiet, open microphone settings and raise input volume.
pause
