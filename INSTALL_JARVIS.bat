@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Install JARVIS HoloDesk

echo ==========================================
echo JARVIS HoloDesk 1.3.5 Installer
echo ==========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python was not found.
  echo Install Python 3.11 or 3.12 from python.org and enable Add Python to PATH.
  pause
  exit /b 1
)

if not exist "payload\main.py" (
  echo ERROR: payload\main.py is missing. Extract the complete ZIP first.
  pause
  exit /b 1
)

if not exist "payload\.venv\Scripts\python.exe" (
  echo Creating the JARVIS Python environment...
  python -m venv "payload\.venv"
  if errorlevel 1 goto :fail
)

echo Installing JARVIS, voice and Windows-control packages...
"payload\.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"payload\.venv\Scripts\python.exe" -m pip install -r "payload\requirements.txt"
if errorlevel 1 goto :fail

echo.
echo Installation complete.
echo Run START_JARVIS.bat, or START_WAKE_LAUNCHER.bat for the welcome voice trigger.
pause
exit /b 0

:fail
echo.
echo Installation failed. Keep this window open and send a screenshot of the error.
pause
exit /b 1
