@echo off
REM ============================================================================
REM  EyE Care - install dependencies
REM
REM  ---------------------------------------------------------------------------
REM  ASCII-ONLY BY DESIGN. DO NOT PUT NON-ASCII TEXT IN THIS FILE.
REM  Not in echo lines, not in prompts, NOT EVEN IN REM COMMENTS.
REM  ---------------------------------------------------------------------------
REM  cmd.exe reads a batch file in byte-sized chunks but re-seeks by character
REM  count, so a CJK character desynchronises the parser: lines get chopped
REM  mid-way and the tail fragment is executed as a command. Observed on a
REM  Japanese (CP932) system, with the fragment coming from a REM comment line.
REM  "chcp 65001" does NOT fix it - it only changes the console code page, not
REM  how cmd tracks its position while reading the file.
REM  Chinese UI belongs in scripts\menu.py, never in a .bat.
REM  Guarded by tests\test_bat_encoding.py.
REM ============================================================================
setlocal EnableExtensions
cd /d "%~dp0.."

echo ========================================
echo   EyE Care - install dependencies
echo ========================================
echo.

if not exist "requirements.txt" goto :no_req

REM ---- locate a usable interpreter (same order as menu.bat) ----
set "PY="
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if defined PY goto :py_ok
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if defined PY goto :py_ok
if exist "D:\Python\python.exe" set "PY=D:\Python\python.exe"
if defined PY goto :py_ok
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :py_ok
where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if defined PY goto :py_ok
goto :no_python

:py_ok
echo Interpreter: %PY%
%PY% --version
if errorlevel 1 goto :bad_python
echo.

echo Upgrading pip ...
%PY% -m pip install --upgrade pip
echo.

echo Installing from requirements.txt ...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo [OK] Dependencies installed.
echo.
pause
exit /b 0

:no_req
echo [X] requirements.txt not found.
echo.
pause
exit /b 1

:no_python
echo [X] No usable Python found.
echo     Install Python 3.12+ with "Add python.exe to PATH",
echo     or create venv\ in the project folder, then retry.
echo.
pause
exit /b 1

:bad_python
echo [X] Python command is not usable: %PY%
echo.
pause
exit /b 1

:failed
echo.
echo [X] Installation failed. Check the Python version and network, then retry.
echo.
pause
exit /b 1
