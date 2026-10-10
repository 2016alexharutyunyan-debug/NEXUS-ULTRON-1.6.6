@echo off
setlocal EnableExtensions
title Uninstall JARVIS Wake Launcher

set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\JARVIS Wake Launcher.lnk"
if exist "%LINK%" del "%LINK%"

echo Removed from Windows Startup.
pause
