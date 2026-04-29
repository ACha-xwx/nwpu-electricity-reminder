@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if %errorlevel%==0 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if %errorlevel%==0 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo 未找到 Python 3。
    echo 请先安装 Python 3，然后再重新运行这个脚本。
    pause
    exit /b 1
)

%PYTHON_CMD% check_electricity.py
set "EXIT_CODE=%errorlevel%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo 这次检查没有成功，请先看看上面的提示信息。
    pause
)

exit /b %EXIT_CODE%
