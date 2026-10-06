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
REM Call the venv entry point directly. We DO NOT use `uv run`: it re-resolves
REM the environment on every launch, which costs seconds of startup and fails
REM outright with no network. The venv entry point needs neither.
"%REPO_DIR%\.venv\Scripts\camoufox-pm.exe" --desktop
echo.
echo [launch.bat] Exit code: %ERRORLEVEL%
pause
endlocal
