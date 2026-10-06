@echo off
REM Camoufox Profile Manager launcher (debug: with console window)
setlocal
set "REPO_DIR=%~dp0"
if "%REPO_DIR:~-1%"=="\" set "REPO_DIR=%REPO_DIR:~0,-1%"
set "CPM_DB_PATH=%REPO_DIR%\data\profiles.db"
cd /d "%REPO_DIR%"
echo [launch.bat] REPO_DIR=%REPO_DIR%
echo [launch.bat] CPM_DB_PATH=%CPM_DB_PATH%
echo.
REM Call the venv entry point directly. We DO NOT use `uv run` because it
REM re-syncs from pyproject.toml, which replaces the release wheel (that
REM ships the compiled Next.js UI) with an editable install missing the UI.
"%REPO_DIR%\.venv\Scripts\camoufox-pm.exe" --desktop
echo.
echo [launch.bat] Exit code: %ERRORLEVEL%
pause
endlocal
