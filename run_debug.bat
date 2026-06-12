@echo off
setlocal
cd /d "%~dp0"

set EYECARE_DEBUG_CONSOLE=1
set EYECARE_CONSOLE_LOG=1
set EYECARE_DEBUG=1
set EYECARE_DEBUG_MODULES=notify,rest,style,dispatch,api,repo,runtime

:: 优先使用项目虚拟环境，否则使用系统 Python（D:\Python）
if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    set "PY=D:\Python\python.exe"
)

"%PY%" main.py --debug --host qt %*