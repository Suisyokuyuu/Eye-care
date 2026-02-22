@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
cd /d "%ROOT%"

echo Cleaning __pycache__ (skip user_data\ venv\ .venv) ...

for /d /r "%ROOT%" %%d in (*) do (
  if /i "%%~nxd"=="__pycache__" (
    echo %%~fd | findstr /i /c:"\user_data\" /c:"\venv\" /c:"\.venv\" >nul && (
      echo SKIP: %%d
    ) || (
      echo DEL : %%d
      rd /s /q "%%d"
    )
  )
)

echo Done.
pause