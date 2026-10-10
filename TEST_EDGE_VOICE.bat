@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ULTRON Edge Neural Voice Test

set "JARVIS_EDGE_VOICE=en-US-GuyNeural"
set "JARVIS_EDGE_RATE=-6%%"
set "JARVIS_EDGE_PITCH=-20Hz"

if exist "payload\.venv\Scripts\python.exe" (
  set "PY=payload\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" payload\test_edge_voice.py
pause
