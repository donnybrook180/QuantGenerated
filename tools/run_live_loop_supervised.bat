@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "RESTART_DELAY_SECONDS=%~1"
if not defined RESTART_DELAY_SECONDS set "RESTART_DELAY_SECONDS=15"

set "MAX_RESTARTS=%~2"
if not defined MAX_RESTARTS set "MAX_RESTARTS=0"

set "RUN_ONCE=%~3"
if not defined RUN_ONCE set "RUN_ONCE=0"

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
set "MAIN_SCRIPT=%REPO_ROOT%\main_live_loop.py"
set "TEE_SCRIPT=%REPO_ROOT%\tools\tee_output.py"
set "LOG_DIR=%REPO_ROOT%\artifacts\system\logs"

if not exist "%PYTHON_EXE%" (
    echo Python executable not found: "%PYTHON_EXE%"
    exit /b 1
)

if not exist "%MAIN_SCRIPT%" (
    echo Live loop entrypoint not found: "%MAIN_SCRIPT%"
    exit /b 1
)

if not exist "%TEE_SCRIPT%" (
    echo Tee helper not found: "%TEE_SCRIPT%"
    exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set /a RESTART_COUNT=0

:loop
set "TIMESTAMP=%date%_%time%"
set "TIMESTAMP=%TIMESTAMP:/=-%"
set "TIMESTAMP=%TIMESTAMP:\=-%"
set "TIMESTAMP=%TIMESTAMP::=-%"
set "TIMESTAMP=%TIMESTAMP:.=-%"
set "TIMESTAMP=%TIMESTAMP: =0%"
set "STDOUT_PATH=%LOG_DIR%\live_loop_%TIMESTAMP%.out.log"
set "SUPERVISOR_LOG=%LOG_DIR%\live_loop_supervisor.log"

echo ========================================
echo QuantGenerated live loop supervisor
echo Repo: %REPO_ROOT%
echo Restart: !RESTART_COUNT!
echo Console output: live
echo Supervisor log: %SUPERVISOR_LOG%
echo Session log: %STDOUT_PATH%
echo ========================================
>>"%SUPERVISOR_LOG%" echo [%date% %time%] starting live loop ^(restart=!RESTART_COUNT!^) session_log=%STDOUT_PATH%
pushd "%REPO_ROOT%"
"%PYTHON_EXE%" "%TEE_SCRIPT%" "%STDOUT_PATH%" "%PYTHON_EXE%" -u "%MAIN_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"
popd
>>"%SUPERVISOR_LOG%" echo [%date% %time%] live loop exited with code !EXIT_CODE! session_log=%STDOUT_PATH%
echo Live loop exited with code !EXIT_CODE!

if "%RUN_ONCE%"=="1" exit /b !EXIT_CODE!

set /a RESTART_COUNT+=1
if not "%MAX_RESTARTS%"=="0" (
    if !RESTART_COUNT! GEQ %MAX_RESTARTS% (
        >>"%SUPERVISOR_LOG%" echo [%date% %time%] reached MAX_RESTARTS=%MAX_RESTARTS%, stopping supervisor
        echo Reached MAX_RESTARTS=%MAX_RESTARTS%, stopping supervisor
        exit /b !EXIT_CODE!
    )
)

echo Restarting in %RESTART_DELAY_SECONDS% seconds...
timeout /t %RESTART_DELAY_SECONDS% /nobreak >nul
goto :loop
