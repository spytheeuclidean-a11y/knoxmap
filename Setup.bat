@echo off
rem KnoxMap one-time setup. Safe to run again.
setlocal
cd /d "%~dp0"

rem Prefer the py launcher; "python" on a fresh Windows can be the Microsoft
rem Store stub, which opens the Store instead of running anything. Either way
rem the version check below is what decides.
set PY=
where py >nul 2>nul && py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set PY=py -3
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set PY=python
if not defined PY (
  echo Python 3.10 or newer is needed. Get it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during install, then run Setup.bat again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment...
  %PY% -m venv .venv || goto :fail
)
echo Installing Python packages...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

".venv\Scripts\python.exe" knoxmap_setup.py || goto :fail
echo.
if not "%KNOXMAP_NO_PAUSE%"=="1" pause
exit /b 0

:fail
echo.
echo Setup stopped with an error - see the messages above.
if not "%KNOXMAP_NO_PAUSE%"=="1" pause
exit /b 1
