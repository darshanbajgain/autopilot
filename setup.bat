@echo off
rem Autopilot setup for Windows. Double-click this file, or run:  setup.bat
setlocal
cd /d "%~dp0"
echo == Autopilot setup ==

set "PY="
where py >nul 2>nul && (py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul && set "PY=py -3")
if not defined PY (
  where python >nul 2>nul && (python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul && set "PY=python")
)
if not defined PY (
  echo Python 3.9 or newer is needed.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
%PY% --version

if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment in .venv ...
  %PY% -m venv .venv || ( echo Couldn't create it. & pause & exit /b 1 )
)

echo Installing packages (a minute or two) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || ( echo Install failed. & pause & exit /b 1 )

set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=1"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=1"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=1"
if not defined CHROME (
  echo.
  echo Google Chrome wasn't found. Install it from https://www.google.com/chrome/
  echo or use "channel: msedge" in your settings to use Microsoft Edge instead.
)

echo.
echo Done.
call "%~dp0autopilot.bat" doctor
echo.
set "MAKE=y"
set /p "MAKE=Create your first automation now? [Y/n] "
if /i "%MAKE%"=="n" (
  echo Later, open a terminal in this folder and run:  autopilot
) else (
  call "%~dp0autopilot.bat" setup
)
pause
