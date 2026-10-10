@echo off
setlocal EnableExtensions
title ULTRON Gemini Quality Voice Mode

echo Setting ULTRON voice priority to GEMINI QUALITY.
echo Quality mode tries Gemini voice first. It may sound better, but it can be slower than 3-5 seconds.
echo.

setx JARVIS_VOICE_PRIORITY gemini
setx JARVIS_VOICE_RECORD_SECONDS 3.5
setx JARVIS_AI_TIMEOUT_SECONDS 15
setx JARVIS_AI_MAX_OUTPUT_TOKENS 180
setx JARVIS_GEMINI_TTS_TIMEOUT_SECONDS 10
setx JARVIS_EDGE_TTS_TIMEOUT_SECONDS 10
setx JARVIS_GEMINI_TTS_VOICE Charon

echo.
echo Done. Close and reopen NEXUS ULTRON.
pause
