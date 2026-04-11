@echo off
setlocal EnableExtensions

set "TASK_NAME=%~1"
if not defined TASK_NAME set "TASK_NAME=QuantGenerated Live Health Report"

set "TIME_VALUE=%~2"
if not defined TIME_VALUE set "TIME_VALUE=23:55"

set "SCRIPT_PATH=%~dp0run_live_health_report.bat"
if not exist "%SCRIPT_PATH%" (
    echo Runner script not found: "%SCRIPT_PATH%"
    exit /b 1
)

echo %TIME_VALUE%| findstr /r "^[0-2][0-9]:[0-5][0-9]$" >nul
if errorlevel 1 (
    echo Time must be in HH:MM format.
    exit /b 1
)

for /f "tokens=1,2 delims=:" %%A in ("%TIME_VALUE%") do (
    set /a HOUR=%%A
    set /a MINUTE=%%B
)

if %HOUR% GTR 23 (
    echo Time must be in HH:MM format.
    exit /b 1
)

schtasks /Create /F /TN "%TASK_NAME%" /SC DAILY /ST %TIME_VALUE% /RL HIGHEST /TR "\"%SCRIPT_PATH%\""
if errorlevel 1 exit /b %ERRORLEVEL%

echo Scheduled task registered: %TASK_NAME% at %TIME_VALUE%
