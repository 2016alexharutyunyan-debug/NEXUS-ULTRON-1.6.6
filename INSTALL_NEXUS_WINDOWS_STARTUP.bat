@echo off
setlocal
cd /d "%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LINK=%STARTUP%\NEXUS.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LINK%');$s.TargetPath='%CD%\START_NEXUS.bat';$s.WorkingDirectory='%CD%';$s.WindowStyle=7;$s.Description='Start NEXUS with Windows';$s.Save()"
echo NEXUS will now start with Windows.
pause
