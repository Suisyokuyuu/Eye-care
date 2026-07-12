@echo off
setlocal
REM 本脚本在 scripts\ 下，先回到项目根目录再构建
cd /d "%~dp0.."

:: 清理源码 __pycache__，确保打包分析用最新代码、产物无陈旧缓存
echo Clearing __pycache__...
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

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
set DISTDIR=%CD%\dist\EyE Care
set INTERNAL=%DISTDIR%\_internal

REM 把按路径加载的资源复制到外层（PROJECT_ROOT/ASSETS_DIR 在 frozen 下指向 exe 同级）。
REM 现在 _internal\eye_care 只含 qt_quick\qml + assets（spec 已改为只打这两样），故外层很干净。
if exist "%INTERNAL%\eye_care" xcopy /e /i /y "%INTERNAL%\eye_care" "%DISTDIR%\eye_care"
if exist "%INTERNAL%\docs" xcopy /e /i /y "%INTERNAL%\docs" "%DISTDIR%\docs"
if exist "%INTERNAL%\icon.ico" copy /y "%INTERNAL%\icon.ico" "%DISTDIR%\"
if exist "%INTERNAL%\icon.png" copy /y "%INTERNAL%\icon.png" "%DISTDIR%\"
if exist "%INTERNAL%\README.md" copy /y "%INTERNAL%\README.md" "%DISTDIR%\"

REM 创建 user_data 目录（首次运行也会自动建）
if not exist "%DISTDIR%\user_data" mkdir "%DISTDIR%\user_data"

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
echo   - eye_care\          (QML + 声音资源，按路径加载)
echo   - docs\使用手册.md   (User manual)
echo   - icon.ico / icon.png
echo.
pause