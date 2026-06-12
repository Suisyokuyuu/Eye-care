@echo off
setlocal
cd /d "%~dp0"

:: 优先使用项目虚拟环境，否则使用系统 Python（D:\Python）
if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    set "PY=D:\Python\python.exe"
)

:: 检查 Python 可用性
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
set DISTDIR=%~dp0dist\EyE Care
set INTERNAL=%DISTDIR%\_internal

REM Copy resources to outer level (preserve original directory structure)
if exist "%INTERNAL%\eye_care" xcopy /e /i /y "%INTERNAL%\eye_care" "%DISTDIR%\eye_care"
if exist "%INTERNAL%\docs" xcopy /e /i /y "%INTERNAL%\docs" "%DISTDIR%\docs"
if exist "%INTERNAL%\icon.ico" copy /y "%INTERNAL%\icon.ico" "%DISTDIR%\"
if exist "%INTERNAL%\icon.png" copy /y "%INTERNAL%\icon.png" "%DISTDIR%\"

REM Copy config files to outer level
if exist "%INTERNAL%\requirements.txt" copy /y "%INTERNAL%\requirements.txt" "%DISTDIR%\"
if exist "%INTERNAL%\README.md" copy /y "%INTERNAL%\README.md" "%DISTDIR%\"

REM Create user_data directory (user data directory)
if not exist "%DISTDIR%\user_data" mkdir "%DISTDIR%\user_data"

REM Copy packaging helper scripts to output directory (exclude run_debug.bat from final package)
if exist "%~dp0install_deps.bat" copy /y "%~dp0install_deps.bat" "%DISTDIR%\"

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo Output directory: %DISTDIR%
echo.
echo Directory structure:
echo   - EyE Care.exe       (Entry program)
echo   - _internal\         (PyInstaller runtime files)
echo   - user_data\         (User data directory)
echo   - eye_care\         (Program modules)
echo   - docs\             (Documentation)
echo   - icon.ico          (Application icon)
echo   - icon.png          (Icon)
echo   - *.bat             (Helper scripts)
echo.
pause