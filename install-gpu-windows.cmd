@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please install the application first. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\install_runtime.py
if errorlevel 1 (
  echo Installation failed. See the error above.
) else (
  echo WhisperLiveKit and Qwen GPU runtime installed. Restart LinguaFlow.
)
pause
