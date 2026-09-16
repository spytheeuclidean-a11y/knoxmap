@echo off
rem KnoxMap one-time setup. Safe to run again.
setlocal
cd /d "%~dp0"

rem Prefer the py launcher; "python" on a fresh Windows can be the Microsoft
rem Store stub, which opens the Store instead of running anything. Either way
rem the version check below is what decides.
set PY=
if exist ".python\tools\python.exe" set PY=".python\tools\python.exe"
if not defined PY where py >nul 2>nul && py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set PY=py -3
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set PY=python
if not defined PY call :portable_python || goto :fail

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

:portable_python
rem No Python on this PC: fetch the official python.org build that is published
rem as a NuGet package (a plain zip with venv and pip), check its fingerprint and
rem keep it inside the KnoxMap folder. Nothing is installed system-wide.
echo Python 3.10 or newer was not found - downloading a private copy (about 14 MB)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; $z='.python.zip'; Invoke-WebRequest -UseBasicParsing 'https://api.nuget.org/v3-flatcontainer/python/3.13.7/python.3.13.7.nupkg' -OutFile $z; if ((Get-FileHash $z -Algorithm SHA256).Hash -ne 'e74272a824e23702dfb5f3e11c3660ceabac7487e3366d4551391db5cd762853') { Remove-Item $z; throw 'The Python download did not match its fingerprint.' }; if (Test-Path '.python') { Remove-Item -Recurse -Force '.python' }; Expand-Archive $z '.python'; Remove-Item $z" || exit /b 1
if not exist ".python\tools\python.exe" exit /b 1
set PY=".python\tools\python.exe"
exit /b 0
