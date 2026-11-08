@echo off
REM Сборка портативной версии: dist\tbank\tbank.exe + data рядом с exe.
REM ВАЖНО: данные из dist\tbank\data сохраняются при пересборке.
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] venv not found: %PY%
    pause
    exit /b 1
)

set "DATABAK=%TEMP%\tbank-portable-data-backup"
if exist "dist\tbank\data" (
    echo Сохраняю текущие данные портативной сборки...
    if exist "%DATABAK%" rmdir /s /q "%DATABAK%"
    xcopy /e /i /y "dist\tbank\data" "%DATABAK%" >nul
)

echo Собираю tbank.exe (PyInstaller, onedir)...
"%PY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name tbank ^
    --icon "%~dp0icon.ico" --exclude-module tkinter --log-level WARN ^
    "%~dp0main.py"
if errorlevel 1 (
    echo [ERROR] сборка не удалась
    pause
    exit /b 1
)

if exist "dist\tbank\data" rmdir /s /q "dist\tbank\data"
mkdir "dist\tbank\data"
if exist "%DATABAK%" (
    xcopy /e /i /y "%DATABAK%" "dist\tbank\data" >nul
    rmdir /s /q "%DATABAK%"
) else (
    echo Данные не найдены: положите tbank.db в dist\tbank\data
)

echo.
echo Готово: %~dp0dist\tbank\tbank.exe
echo Данные (tbank.db, backups, .moy-nalog-session.json): dist\tbank\data
pause
