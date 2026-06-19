@echo off
REM ============================================================
REM  EyE Care - 启动真实应用（QML 原生外壳，debug 模式）
REM  这不是预览沙箱：含托盘 / 休息遮罩 / 真实配置落盘等。
REM  控制台保持可见，便于读 qt.qml_shell.* / qt.tray.* 日志。
REM    scripts\run_qml_shell.bat   启动应用（可见控制台 + 日志）
REM  本脚本在 scripts\ 下，先回到项目根目录再运行。
REM ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0.."

set PYTHONUTF8=1
set EYECARE_CONSOLE_LOG=1

set "CANDIDATES=D:\Python\python.exe venv\Scripts\python.exe .venv\Scripts\python.exe python.exe"

for %%P in (%CANDIDATES%) do (
    "%%P" -c "import PySide6" 1>nul 2>nul
    if not errorlevel 1 (
        echo [run] interpreter: %%P
        "%%P" main.py --host qt --debug --no-single
        goto :done
    )
)

for %%V in (3.14 3.13 3.12 3) do (
    py -%%V -c "import PySide6" 1>nul 2>nul
    if not errorlevel 1 (
        echo [run] interpreter: py -%%V
        py -%%V main.py --host qt --debug --no-single
        goto :done
    )
)

echo.
echo [ERROR] No Python with PySide6 found. Run and send me:
echo        D:\Python\python.exe -c "import PySide6; print(PySide6.__file__)"
:done
echo.
echo [run_qml_shell] process exited. If there is a traceback above, paste it to me.
endlocal
pause
