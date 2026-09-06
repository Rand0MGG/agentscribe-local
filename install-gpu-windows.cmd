@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please install the application first. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -e ".[gpu]"
if errorlevel 1 (
  echo Installation failed. See the error above.
) else (
  echo GPU libraries installed. Restart LinguaFlow.
)
pause
