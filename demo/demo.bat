@echo off
rem ============================================================
rem  EasyRouter demo launcher for Windows
rem  Keep this file ASCII-only with CRLF line endings.
rem ============================================================
setlocal
cd /d "%~dp0.."
if defined EASYROUTER_NO_BROWSER (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo.ps1" -NoBrowser
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo.ps1"
)
echo.
pause
endlocal
