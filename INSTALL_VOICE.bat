@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title JARVIS Voice Installer

echo ==========================================
echo JARVIS Voice Installer
echo ==========================================
echo.
echo Installing neural voice and microphone recognition packages...
echo This keeps API keys out of the project.
echo.

if exist "payload\.venv\Scripts\python.exe" (
  set "PY=payload\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install google-genai edge-tts sounddevice SpeechRecognition numpy

echo.
echo Done.
echo Next:
echo 1. Run TEST_GEMINI_VOICE.bat
echo 2. Run TEST_EDGE_VOICE.bat
echo 3. Run TEST_SPEAKER.bat
echo 4. Run TEST_MICROPHONE.bat
echo 5. Run START_JARVIS.bat
pause
