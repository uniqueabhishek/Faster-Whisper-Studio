@echo off
cd /d "%~dp0"
echo Starting Faster Whisper License Manager (VENDOR ONLY)...
echo Current directory: %cd%

REM Try to run with uv
where uv >nul 2>&1
if %errorlevel% equ 0 (
    echo Using uv...
    uv run python license_manager_app.py
) else (
    echo uv not found in PATH, trying python directly...
    python license_manager_app.py
)

if %errorlevel% neq 0 (
    echo.
    echo ERROR: License Manager failed to start!
    echo Make sure you have uv or Python installed and in PATH,
    echo and that admin_keys\private_key.pem exists (run setup_security.py if not).
)
pause
