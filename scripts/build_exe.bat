@echo off
setlocal

cd /d "%~dp0.."

echo Clearing __pycache__...
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    set "PY=D:\Python\python.exe"
)

"%PY%" --version >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python and add to PATH.
    pause
    exit /b 1
)

echo Installing dependencies...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo pip install failed.
    pause
    exit /b 1
)

echo Checking PyInstaller...
"%PY%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    "%PY%" -m pip install pyinstaller
    if errorlevel 1 (
        echo PyInstaller install failed.
        pause
        exit /b 1
    )
)

if not exist "main.py" (echo main.py not found. & pause & exit /b 1)
if not exist "version_info.txt" (echo version_info.txt not found. & pause & exit /b 1)
if not exist "icon.ico" (echo icon.ico not found. & pause & exit /b 1)

echo Building with spec file...
"%PY%" -m PyInstaller "EyE Care.spec" --noconfirm --clean

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