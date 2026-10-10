@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Install JARVIS Wake Launcher

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LINK=%STARTUP%\JARVIS Wake Launcher.lnk"
set "TARGET=%CD%\START_WAKE_LAUNCHER.bat"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LINK%'); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%CD%'; $s.WindowStyle=7; $s.Save()"

echo Installed. The wake launcher will start when Windows starts.
echo You can also run START_WAKE_LAUNCHER.bat manually.
pause
