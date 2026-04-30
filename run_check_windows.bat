@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo A working Python 3 interpreter was not found.
    echo.
    echo If you see an error like:
    echo Unable to create process using 'C:\Python314\python.exe'
    echo it usually means the py launcher points to an old Python path.
    echo.
    echo Please reinstall Python 3 and make sure python.exe works in PowerShell.
    pause
    exit /b 1
)

echo Starting electricity check...
echo.
%PYTHON_CMD% check_electricity.py
set "EXIT_CODE=%errorlevel%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo Electricity check failed.
) else (
    echo Electricity check finished.
)

echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%
