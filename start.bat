@echo off
rem AI_NovelGenerator launcher - uses project venv ONLY
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project venv not found. Run setup first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
