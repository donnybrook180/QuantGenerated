@echo off
setlocal DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "ENV_FILE=%SCRIPT_DIR%.env"

if not exist "%ENV_FILE%" (
    echo .env not found: "%ENV_FILE%"
    exit /b 1
)

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if /I "%%A"=="MT5_LOGIN" set "MT5_LOGIN=%%B"
    if /I "%%A"=="MT5_PASSWORD" set "MT5_PASSWORD=%%B"
    if /I "%%A"=="MT5_SERVER" set "MT5_SERVER=%%B"
    if /I "%%A"=="MT5_TERMINAL_PATH" set "MT5_TERMINAL_PATH=%%B"
)

set "MT5_LOGIN=%MT5_LOGIN:"=%"
set "MT5_PASSWORD=%MT5_PASSWORD:"=%"
set "MT5_SERVER=%MT5_SERVER:"=%"
set "MT5_TERMINAL_PATH=%MT5_TERMINAL_PATH:"=%"

if not defined MT5_LOGIN (
    echo MT5_LOGIN is missing in .env
    exit /b 1
)

if not defined MT5_PASSWORD (
    echo MT5_PASSWORD is missing in .env
    exit /b 1
)

if not defined MT5_SERVER (
    echo MT5_SERVER is missing in .env
    exit /b 1
)

if not defined MT5_TERMINAL_PATH (
    echo MT5_TERMINAL_PATH is missing in .env
    exit /b 1
)

if not exist "%MT5_TERMINAL_PATH%" (
    echo MT5 terminal not found: "%MT5_TERMINAL_PATH%"
    exit /b 1
)

set "CONFIG_FILE=%TEMP%\quantgenerated_mt5_login.ini"

(
    echo [Common]
    echo Login=%MT5_LOGIN%
    echo Password=%MT5_PASSWORD%
    echo Server=%MT5_SERVER%
    echo KeepPrivate=1
) > "%CONFIG_FILE%"

start "" "%MT5_TERMINAL_PATH%" /config:"%CONFIG_FILE%"
if errorlevel 1 (
    echo Failed to start MT5 terminal.
    exit /b %ERRORLEVEL%
)

timeout /t 5 /nobreak >nul
del "%CONFIG_FILE%" >nul 2>&1

exit /b 0
