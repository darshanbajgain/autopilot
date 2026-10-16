@echo off
rem Runs Autopilot with its own Python environment. Usage: autopilot <command> ...
set "AP_DIR=%~dp0"
if not exist "%AP_DIR%.venv\Scripts\python.exe" (
  echo Autopilot isn't set up yet. Run setup.bat in %AP_DIR% first.
  exit /b 1
)
set "PYTHONPATH=%AP_DIR%src;%PYTHONPATH%"
"%AP_DIR%.venv\Scripts\python.exe" -m autopilot %*
