@echo off
rem Kaigo tool launcher (double-click to run)
rem First run only: create a private Python environment (.venv) in this folder and install libraries
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto run

echo First-time setup. This takes a few minutes...
set "PYEXE="
if exist "%USERPROFILE%\.local\bin\python3.14.exe" set "PYEXE=%USERPROFILE%\.local\bin\python3.14.exe"
if not defined PYEXE if exist "%USERPROFILE%\.local\bin\python.exe" set "PYEXE=%USERPROFILE%\.local\bin\python.exe"
if not defined PYEXE (
    where py > nul 2>&1 && set "PYEXE=py"
)
if not defined PYEXE (
    where python > nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo Python not found. Please install Python 3.11 or later.
    pause
    exit /b 1
)

"%PYEXE%" -m venv .venv
if errorlevel 1 (
    echo Failed to create the Python environment.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install libraries.
    rmdir /s /q .venv
    pause
    exit /b 1
)

:run
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
