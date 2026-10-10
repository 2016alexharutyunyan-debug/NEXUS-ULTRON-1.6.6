@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NEXUS ULTRON 1.6.6 RELIABLE TYPING

echo ==========================================
echo NEXUS ULTRON 1.6.6 - RELIABLE AIR TYPING AND PALM BACKSPACE
echo Voice recognition: ON
echo Voice replies: ON
echo Camera: ON while NEXUS is open
echo Hand control: ON
echo ==========================================
echo.

for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v GEMINI_API_KEY 2^>nul ^| findstr GEMINI_API_KEY') do set "GEMINI_API_KEY=%%B"

findstr /L /C:"1.6.6-reliable-typing-and-palm-backspace" "main.py" >nul 2>&1
if errorlevel 1 (
  echo ERROR: ULTRON 1.6.6 update is not installed.
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "main.py"
) else (
  python "main.py"
)

if errorlevel 1 (
  echo.
  echo HoloDesk stopped with an error.
  pause
)
