@echo off
setlocal
cd /d "%~dp0"
set EYECARE_DEBUG_CONSOLE=1
set EYECARE_CONSOLE_LOG=1
set EYECARE_DEBUG=1
set EYECARE_DEBUG_MODULES=notify,rest,style,dispatch,api,repo,runtime
if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    set "PY=python"
)
"%PY%" main.py --debug %*
