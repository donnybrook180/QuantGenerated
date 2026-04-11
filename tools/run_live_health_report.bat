@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
set "MAIN_SCRIPT=%REPO_ROOT%\tools\main_live_health_report.py"
set "LOG_DIR=%REPO_ROOT%\artifacts\system\logs"

if not exist "%PYTHON_EXE%" (
    echo Python executable not found: "%PYTHON_EXE%"
    exit /b 1
)

if not exist "%MAIN_SCRIPT%" (
    echo Live health report entrypoint not found: "%MAIN_SCRIPT%"
    exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "TIMESTAMP=%date%_%time%"
set "TIMESTAMP=%TIMESTAMP:/=-%"
set "TIMESTAMP=%TIMESTAMP:\=-%"
set "TIMESTAMP=%TIMESTAMP::=-%"
set "TIMESTAMP=%TIMESTAMP:.=-%"
set "TIMESTAMP=%TIMESTAMP: =0%"
set "LOG_PATH=%LOG_DIR%\live_health_report_%TIMESTAMP%.log"

pushd "%REPO_ROOT%"
"%PYTHON_EXE%" "%MAIN_SCRIPT%" 1>>"%LOG_PATH%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
popd

exit /b %EXIT_CODE%
