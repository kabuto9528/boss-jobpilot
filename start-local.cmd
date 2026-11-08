@echo off
setlocal
cd /d "%~dp0"
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1"
set "launchResult=%ERRORLEVEL%"
if not "%launchResult%"=="0" pause
exit /b %launchResult%
