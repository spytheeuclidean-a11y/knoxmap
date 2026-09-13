@echo off
rem Launch KnoxMap with the project's virtualenv, no console window.
rem First run? Setup creates the environment and fetches the map tools.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  call Setup.bat
  if errorlevel 1 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "knoxmap.py"
