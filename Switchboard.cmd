@echo off
cd /d "%~dp0"
if exist "%~dp0release\Switchboard.exe" (
  start "" "%~dp0release\Switchboard.exe"
  exit /b
)
where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw "%~dp0launcher.py"
  exit /b
)
python "%~dp0launcher.py"
