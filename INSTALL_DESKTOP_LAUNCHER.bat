@echo off
setlocal
cd /d "%~dp0"
set "LINK=%USERPROFILE%\Desktop\NEXUS.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LINK%');$s.TargetPath='%CD%\START_NEXUS.bat';$s.WorkingDirectory='%CD%';$s.Description='NEXUS with ULTRON';$s.Save()"
echo NEXUS launcher created on the Desktop.
pause
