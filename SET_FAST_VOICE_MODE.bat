@echo off
setlocal EnableExtensions
title ULTRON Fast Voice Mode

echo Setting ULTRON voice priority to FAST.
echo Fast mode uses Edge neural voice first, then Gemini, then Windows fallback.
echo This is the best mode for 3-5 second responses.
echo.

setx JARVIS_VOICE_PRIORITY fast
setx JARVIS_VOICE_RECORD_SECONDS 5.0
setx JARVIS_AI_TIMEOUT_SECONDS 7
setx JARVIS_AI_MAX_OUTPUT_TOKENS 72
setx JARVIS_EDGE_VOICE "en-US-GuyNeural"
setx JARVIS_EDGE_RATE "-6%%"
setx JARVIS_EDGE_PITCH "-20Hz"
setx JARVIS_GEMINI_TTS_TIMEOUT_SECONDS 5
setx JARVIS_EDGE_TTS_TIMEOUT_SECONDS 10

echo.
echo Done. Close and reopen NEXUS ULTRON.
pause
