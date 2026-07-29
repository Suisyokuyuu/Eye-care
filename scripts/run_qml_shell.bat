@echo off
REM ============================================================================
REM  EyE Care - run the real app (native QML shell, debug mode)
REM
REM  This is NOT a preview sandbox: tray icon, rest overlay and real config
REM  persistence are all active. The console stays visible so you can read the
REM  qt.qml_shell.* / qt.tray.* log lines.
REM      scripts\run_qml_shell.bat
REM  The script lives in scripts\, so it first changes back to the project root.
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
chcp 65001 >nul
cd /d "%~dp0.."

REM The app logs contain Chinese; without these, writing them to a CP932
REM console raises UnicodeEncodeError and takes the process down.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set EYECARE_CONSOLE_LOG=1

REM ---- need an interpreter that actually has PySide6 installed ----
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
echo [X] No Python with PySide6 found. Run scripts\install_deps.bat first.
echo     If it still fails, run this and send me the output:
echo         D:\Python\python.exe -c "import PySide6; print(PySide6.__file__)"

:done
echo.
echo [run_qml_shell] process exited. If there is a traceback above, paste it to me.
endlocal
pause
