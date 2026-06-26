@echo off
cd /d "%~dp0"
echo Starting Faster Whisper GUI...
echo Current directory: %cd%

REM Try to run with uv
where uv >nul 2>&1
if %errorlevel% equ 0 (
    echo Using uv...
    uv run python app.py
) else (
    echo uv not found in PATH, trying python directly...
    python app.py
)

if %errorlevel% neq 0 (
    echo.
    echo ERROR: App failed to start!
    echo Make sure you have uv or Python installed and in PATH.
)
pause
