@echo off
setlocal EnableExtensions
title Set Gemini API Key for JARVIS

echo ==========================================
echo Set Gemini API Key for JARVIS
echo ==========================================
echo.
echo Paste your Gemini API key below.
echo It will be saved as the Windows user environment variable GEMINI_API_KEY.
echo The key will NOT be written into the JARVIS code.
echo.

set /p GEMINI_KEY=Gemini API key: 
if "%GEMINI_KEY%"=="" (
  echo No key entered.
  pause
  exit /b 1
)

set "GEMINI_API_KEY=%GEMINI_KEY%"
setx GEMINI_API_KEY "%GEMINI_KEY%"
echo.
echo Saved. Close and reopen JARVIS so Windows loads the new environment variable.
pause
