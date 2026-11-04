@echo off
rem Double-click to start AFH. Creates the virtual environment on first run.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Setting up AFH for the first time...
  py -3.12 -m venv .venv || python -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)
start "" ".venv\Scripts\pythonw.exe" run.py %*
exit /b 0

:fail
echo Setup failed. See the messages above.
pause
exit /b 1
