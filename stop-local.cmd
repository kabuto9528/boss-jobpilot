@echo off
setlocal
cd /d "%~dp0"
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-local.ps1"
set "stopResult=%ERRORLEVEL%"
if not "%stopResult%"=="0" pause
exit /b %stopResult%
