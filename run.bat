@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   tbank desktop launcher
echo ============================================

set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] venv not found: %PY%
    echo Create it: py -3.11 -m venv .venv
    echo Then: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%PY%" main.py %*
if errorlevel 1 pause
