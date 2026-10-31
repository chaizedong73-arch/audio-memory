@echo off
setlocal
cd /d "%~dp0"
set "APP_PYTHON=runtime\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
  echo Environment is not installed. Run install.cmd --vision first.
  exit /b 1
)
echo Watching completed camera videos. Press Ctrl+C to stop.
"%APP_PYTHON%" visual_worker.py --watch
exit /b %errorlevel%
