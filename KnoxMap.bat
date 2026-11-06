@echo off
rem Launch KnoxMap with the project's virtualenv, no console window.
rem First run? Setup creates the environment and fetches the map tools.
cd /d "%~dp0"
rem UTF-8 for every file Python reads and writes, whatever the PC's code page.
rem On a Korean or Japanese Windows the default one cannot hold all of KnoxMap's text.
set PYTHONUTF8=1
if not exist ".venv\Scripts\pythonw.exe" (
  call Setup.bat
)
rem Setup now also exits non-zero for work it could not finish - a rule file it
rem could not write yet is a red row in the window and nothing more - so only a
rem missing environment stops the app from being started.
if not exist ".venv\Scripts\pythonw.exe" (
  echo KnoxMap needs its Python environment, and Setup could not make it.
  echo Run Setup.bat to see why; logs\setup.log has the details.
  if not "%KNOXMAP_NO_PAUSE%"=="1" pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "knoxmap.py"
