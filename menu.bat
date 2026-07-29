@echo off
REM ============================================================================
REM  EyE Care - version / build menu (Windows)
REM
REM  ---------------------------------------------------------------------------
REM  ASCII-ONLY BY DESIGN. DO NOT PUT NON-ASCII TEXT IN THIS FILE.
REM  Not in echo lines, not in prompts, NOT EVEN IN REM COMMENTS.
REM  ---------------------------------------------------------------------------
REM  cmd.exe cannot reliably parse a batch file that contains multi-byte
REM  characters. It reads the file in byte-sized chunks but re-seeks by
REM  character count, so a CJK character desynchronises the parser: lines get
REM  chopped mid-way and the tail fragment is executed as a command. Observed
REM  on a Japanese (CP932) system as errors like:
REM      'ASCII...REM' is not recognized as an internal or external command
REM  where that fragment came from the middle of a REM comment line.
REM
REM  Saving as UTF-8 and adding "chcp 65001" does NOT fix this - it was tried
REM  and it broke. chcp only changes the console code page; it does not change
REM  how cmd tracks its position while reading the file.
REM
REM  Therefore this file stays pure ASCII and does exactly one thing: hand over
REM  to scripts\menu.py. All user-facing Chinese text lives there, because
REM  Python decodes the source as real UTF-8 and has none of these problems.
REM  (Same approach as Video 2 Knowledge's menu.bat, which hands over to a
REM  PowerShell script. Python is used here instead - the build already
REM  requires it, and the logic stays unit-testable.)
REM ============================================================================
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

REM UTF-8 for the child process, so Chinese output survives a CP932 console.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "MENU=scripts\menu.py"
if not exist "%MENU%" goto :no_menu

REM ---- locate a usable interpreter (same order as scripts\run_qml_shell.bat) ----
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
%PY% "%MENU%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :failed
goto :end

:no_menu
echo [X] Missing file: scripts\menu.py
echo     Please re-clone or re-extract the project.
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

:failed
echo.
echo [X] The menu script exited with code %RC%.
pause
exit /b %RC%

:end
endlocal
exit /b 0
