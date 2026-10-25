@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    echo [Fionix] Virtual environment not found.
    echo Create it once with:
    echo     py -3.11 -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

if errorlevel 1 pause
endlocal
