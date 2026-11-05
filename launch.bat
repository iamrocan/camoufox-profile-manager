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
REM Deliberately does NOT go through scripts\prelaunch.py: this is the debug
REM launcher, so it starts the manager and nothing else -- no update check, no
REM pruning, no second process -- and its console shows the manager's own output.
REM Call the venv's signed python.exe on the package, NOT camoufox-pm.exe: pip
REM and uv build that stub on the machine, so it is unsigned and Windows 11's
REM Smart App Control blocks it. We also do not use `uv run`: it re-resolves the
REM environment on every launch, which costs seconds of startup and fails
REM outright with no network. Neither route needs it.
"%REPO_DIR%\.venv\Scripts\python.exe" -m camoufox_pm.cli --desktop
echo.
echo [launch.bat] Exit code: %ERRORLEVEL%
pause
endlocal
