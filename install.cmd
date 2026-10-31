@echo off
if exist "%~dp0runtime\python.exe" (
  "%~dp0runtime\python.exe" "%~dp0material_store.py"
  exit /b
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3.13 -c "import sys; assert sys.version_info[:2] == (3,13)" >nul 2>&1
  if not errorlevel 1 goto use_launcher
)
where python >nul 2>&1
if not errorlevel 1 (
  python -c "import sys; assert sys.version_info[:2] == (3,13)" >nul 2>&1
  if not errorlevel 1 goto use_python
)
echo Python 3.13 not found. Install it from python.org and enable PATH, then retry.
exit /b 1
:use_launcher
py -3.13 "%~dp0setup.py" install %*
exit /b %errorlevel%
:use_python
python "%~dp0setup.py" install %*
exit /b %errorlevel%
