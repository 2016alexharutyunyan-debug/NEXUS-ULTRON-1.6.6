@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title JARVIS Gemini Voice Test

if exist "payload\.venv\Scripts\python.exe" (
  set "PY=payload\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v GEMINI_API_KEY 2^>nul ^| findstr GEMINI_API_KEY') do set "GEMINI_API_KEY=%%B"

"%PY%" payload\test_gemini_voice.py
pause
