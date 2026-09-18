@echo off
REM Mnemify - one-time setup (Windows). Double-click me, or run me from a terminal.
REM
REM Re-running this is also how you update: get the new code, then run this again.
REM -ExecutionPolicy Bypass applies to this one PowerShell process only. Your
REM machine's execution policy is not read, not changed, and not consulted again.

setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" %*
set "MNEMIFY_EXIT=%ERRORLEVEL%"
if not "%MNEMIFY_EXIT%"=="0" (
    echo.
    echo Setup did not finish. The message above says why.
    pause
)
exit /b %MNEMIFY_EXIT%
