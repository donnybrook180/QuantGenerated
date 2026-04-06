@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Python executable not found: "%PYTHON_EXE%"
    exit /b 1
)

"%PYTHON_EXE%" "%SCRIPT_DIR%main_live_loop.py" %*
exit /b %ERRORLEVEL%
