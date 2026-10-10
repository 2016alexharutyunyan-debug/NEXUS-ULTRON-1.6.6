@echo off
setlocal
set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\NEXUS.lnk"
if exist "%LINK%" del /q "%LINK%"
echo NEXUS Windows startup launcher removed.
pause
