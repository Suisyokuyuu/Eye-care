@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   EyE Care - 安装依赖
echo ========================================
echo.

if not exist "requirements.txt" (
    echo [错误] 未找到 requirements.txt
    pause
    exit /b 1
)

:: 优先使用当前目录下的虚拟环境
if exist "venv\Scripts\python.exe" (
    echo 使用虚拟环境: %~dp0venv
    set "PY=venv\Scripts\python.exe"
    set "PIP=venv\Scripts\pip.exe"
) else (
    set "PY=python"
    set "PIP=pip"
)

echo 正在安装: %PIP% install -r requirements.txt
echo.
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt

if %ERRORLEVEL% neq 0 (
    echo.
    echo [失败] 依赖安装出错，请检查 Python 版本与网络。
    pause
    exit /b 1
)

echo.
echo [完成] 依赖已安装。
pause
