@echo off
setlocal

cd /d "%~dp0.."

echo Clearing __pycache__...
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

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

%PY_CMD% --version
if errorlevel 1 (
    echo Python command is not usable: %PY_CMD%
    pause
    exit /b 1
)

echo Checking build dependencies...
%PY_CMD% -c "import PySide6, yaml, psutil, win32api, PyInstaller"
if errorlevel 1 (
    echo Build dependencies are missing.
    echo Run scripts\install_deps.bat first, then retry this build.
    pause
    exit /b 1
)

if not exist "main.py" (echo main.py not found. & pause & exit /b 1)
if not exist "icon.ico" (echo icon.ico not found. & pause & exit /b 1)

REM version_info.txt is generated from eye_care\version.py - never edit it by hand.
REM Regenerating here keeps the exe properties in sync even when building directly
REM (menu.bat does the same). Use menu.bat option 1 to change the version number.
echo Syncing version info...
%PY_CMD% scripts\sync_version.py
if errorlevel 1 (
    echo Failed to generate version_info.txt from eye_care\version.py.
    pause
    exit /b 1
)

echo Building with spec file...
%PY_CMD% -m PyInstaller "EyE Care.spec" --noconfirm --clean

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo Fixing directory structure...
set DISTDIR=%CD%\dist\EyE Care
set INTERNAL=%DISTDIR%\_internal

if exist "%INTERNAL%\eye_care" xcopy /e /i /y "%INTERNAL%\eye_care" "%DISTDIR%\eye_care"
if exist "%INTERNAL%\icon.ico" copy /y "%INTERNAL%\icon.ico" "%DISTDIR%\"
if exist "%INTERNAL%\icon.png" copy /y "%INTERNAL%\icon.png" "%DISTDIR%\"
if exist "%INTERNAL%\README.md" copy /y "%INTERNAL%\README.md" "%DISTDIR%\"

if not exist "%DISTDIR%\user_data" mkdir "%DISTDIR%\user_data"

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo.
pause
