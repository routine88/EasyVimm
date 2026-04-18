@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title EasyVimm

echo.
echo  ============================================
echo    EasyVimm - Vimm's Lair ROM Downloader
echo  ============================================
echo.

REM --- Check for Python ---
set PYTHON_EXE=python
where %PYTHON_EXE% >nul 2>nul
if errorlevel 1 (
    set PYTHON_EXE=py
    where !PYTHON_EXE! >nul 2>nul
    if errorlevel 1 (
        goto :python_missing
    )
)

REM --- Detect the Windows Store placeholder.
REM     On Win10/11 with no real Python, 'python' opens the Microsoft Store
REM     instead of running. `python --version` prints nothing in that case.
for /f "tokens=*" %%v in ('%PYTHON_EXE% --version 2^>nul') do set PY_VERSION=%%v
if not defined PY_VERSION goto :python_missing
echo %PY_VERSION% | findstr /R /C:"^Python [3-9]" >nul
if errorlevel 1 goto :python_missing
goto :python_ok

:python_missing
echo [X] Python 3.10 or newer is not installed on this computer.
echo.
echo To use EasyVimm you need real Python from python.org
echo ^(not the Microsoft Store placeholder^).
echo.
echo I'll open the download page in your browser now.
echo.
echo IMPORTANT: When you install Python, check the box that says
echo             "Add python.exe to PATH"
echo            before you click Install.
echo.
start https://www.python.org/downloads/
echo After Python is installed, close this window and double-click
echo EasyVimm.bat again.
echo.
pause
exit /b 1

:python_ok

REM --- First-run: create virtual environment ---
if not exist ".venv\Scripts\python.exe" (
    echo [*] First-time setup: creating virtual environment...
    %PYTHON_EXE% -m venv .venv
    if errorlevel 1 (
        echo [X] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

REM --- Install / update dependencies (quiet, only shows errors) ---
echo [*] Making sure required packages are installed...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo [X] Could not install required packages. Check your internet connection.
    pause
    exit /b 1
)

REM --- Self-update: git pull for git clones, GitHub zip overlay otherwise ---
echo [*] Checking for updates...
".venv\Scripts\python.exe" -m easyvimm.updater

echo.
echo [*] Starting EasyVimm... a browser window will open in a moment.
echo     Keep this window open while you download games.
echo     Close this window when you are done.
echo.

".venv\Scripts\python.exe" app.py

echo.
echo EasyVimm has stopped. You can close this window.
pause
