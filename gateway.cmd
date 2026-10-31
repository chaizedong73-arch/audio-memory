@echo off
setlocal
cd /d "%~dp0"
set "APP_PYTHON=runtime\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
  echo Environment is not installed. Run install.cmd first.
  exit /b 1
)
echo Starting local gateway. Press Ctrl+C to stop.
"%APP_PYTHON%" ai_material_gateway.py serve %*
exit /b %errorlevel%
