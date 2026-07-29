@echo off
REM Double-clickable wrapper for update_data.ps1 (see that file for switches).
REM Any args are passed through, e.g.:  update_data.bat -DryRun
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_data.ps1" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
