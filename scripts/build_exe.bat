@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PY_CMD="
if exist "venv\Scripts\python.exe" set PY_CMD="venv\Scripts\python.exe"
if not defined PY_CMD if exist ".venv\Scripts\python.exe" set PY_CMD=".venv\Scripts\python.exe"
if not defined PY_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3.14"
)
if not defined PY_CMD (
    echo Python not found. Install Python 3.14 or create venv\.
    pause
    exit /b 1
)
%PY_CMD% -B scripts\build_exe.py
set "BUILD_RC=%ERRORLEVEL%"
pause
exit /b %BUILD_RC%
