@echo off
REM ============================================================
REM  CipherChat - one-click setup & launcher
REM  Works on any Windows PC that has Python 3.10+ installed.
REM  First run : creates .venv + installs dependencies + starts
REM  Next runs : skips setup, just starts the server
REM  To share the project, send the folder WITHOUT .venv or
REM  __pycache__ (see .gitignore) - this script rebuilds them.
REM ============================================================

setlocal
cd /d "%~dp0"
title CipherChat

echo.
echo  ==============================================
echo    CipherChat - Real-Time Encrypted Chat
echo  ==============================================
echo.

REM ---------- [1/4] Locate a working Python ----------
set "PYTHON="
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -c "import sys" >nul 2>nul && set "PYTHON=py -3"
)
if not defined PYTHON (
    where python >nul 2>nul
    if %errorlevel%==0 (
        REM the "python" from the Microsoft Store stub fails this check, so we test it
        python -c "import sys" >nul 2>nul && set "PYTHON=python"
    )
)
if not defined PYTHON (
    echo  [ERROR] Python was not found on this PC.
    echo.
    echo  Install Python 3.10 or newer from:
    echo      https://www.python.org/downloads/
    echo.
    echo  IMPORTANT during install: tick "Add python.exe to PATH".
    echo  Then run this file again.
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('%PYTHON% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%v"
echo  [1/4] Python %PYVER% found.

REM ---------- [2/4] Create virtual environment (first run only) ----------
if exist ".venv\Scripts\python.exe" goto venv_ok
echo  [2/4] Creating virtual environment .venv (one time, ~10s)...
%PYTHON% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo  [ERROR] Failed to create the virtual environment.
    pause
    exit /b 1
)
goto venv_done
:venv_ok
echo  [2/4] Virtual environment already exists - skipping.
:venv_done

set "VENV_PY=.venv\Scripts\python.exe"

REM ---------- [3/4] Install dependencies ----------
REM  pip skips anything already installed, so this is fast on re-runs
echo  [3/4] Installing / checking dependencies...
"%VENV_PY%" -m pip install --quiet --upgrade pip
"%VENV_PY%" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Dependency install failed. Check your internet
    echo  connection, or try:  "%VENV_PY%" -m pip install -r requirements.txt
    pause
    exit /b 1
)

REM ---------- [4/4] Start the server ----------
echo.
echo  [4/4] Starting CipherChat...
echo.
echo      App URL : http://127.0.0.1:8000
echo      Rooms   : open the URL in two tabs/devices, join the
echo                same room code to chat.
echo.
echo  Leave this window open while chatting.
echo  Press Ctrl+C (or close the window) to stop the server.
echo.
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8000
"%VENV_PY%" -m uvicorn main:app --host 127.0.0.1 --port 8000

echo.
echo  Server stopped.
pause
