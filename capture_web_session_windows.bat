@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if %errorlevel%==0 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python 3 was not found.
    echo Please install Python 3 and try again.
    pause
    exit /b 1
)

echo Starting browser session capture...
echo A browser window should open next if everything is working.
echo.
%PYTHON_CMD% capture_web_session.py
set "EXIT_CODE=%errorlevel%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo Browser session capture failed.
) else (
    echo Browser session capture finished.
)

echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%
