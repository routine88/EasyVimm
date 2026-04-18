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
        echo [X] Python is not installed on this computer.
        echo.
        echo To use EasyVimm you need Python 3.10 or newer.
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
    )
)

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
