@echo off
setlocal EnableExtensions

set "TASK_NAME=%~1"
if not defined TASK_NAME set "TASK_NAME=QuantGenerated Live Loop"

set "TRIGGER_TYPE=%~2"
if not defined TRIGGER_TYPE set "TRIGGER_TYPE=AtLogon"

set "RESTART_DELAY_SECONDS=%~3"
if not defined RESTART_DELAY_SECONDS set "RESTART_DELAY_SECONDS=15"

set "MAX_RESTARTS=%~4"
if not defined MAX_RESTARTS set "MAX_RESTARTS=0"

if /I not "%TRIGGER_TYPE%"=="AtLogon" if /I not "%TRIGGER_TYPE%"=="AtStartup" (
    echo TriggerType must be AtLogon or AtStartup.
    exit /b 1
)

set "SCRIPT_PATH=%~dp0run_live_loop_supervised.bat"
if not exist "%SCRIPT_PATH%" (
    echo Runner script not found: "%SCRIPT_PATH%"
    exit /b 1
)

if /I "%TRIGGER_TYPE%"=="AtStartup" (
    schtasks /Create /F /TN "%TASK_NAME%" /SC ONSTART /RL HIGHEST /TR "\"%SCRIPT_PATH%\" %RESTART_DELAY_SECONDS% %MAX_RESTARTS%"
) else (
    schtasks /Create /F /TN "%TASK_NAME%" /SC ONLOGON /RL HIGHEST /TR "\"%SCRIPT_PATH%\" %RESTART_DELAY_SECONDS% %MAX_RESTARTS%"
)

if errorlevel 1 exit /b %ERRORLEVEL%

echo Scheduled task registered: %TASK_NAME% (%TRIGGER_TYPE%)
