@echo off
REM Mnemify - start the app (Windows).
REM Anything you pass is handed to the server, e.g. mnemify.bat --no-browser
REM
REM %* is forwarded verbatim on purpose - no "--" is inserted. PowerShell's
REM -File hands a bare "--" to the script as an empty parameter name and the
REM binder rejects it; "--no-browser" / "--port 8793" bind fine on their own.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\mnemify.ps1" %*
exit /b %ERRORLEVEL%
