@echo off
setlocal
cd /d "%~dp0"
set "APP_PYTHON=runtime\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
  echo Environment is not installed. Run install.cmd first.
  exit /b 1
)
echo Starting recording and transcription. Press Ctrl+C to stop safely.
"%APP_PYTHON%" run_core.py %*
exit /b %errorlevel%
