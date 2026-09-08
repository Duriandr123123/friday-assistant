@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.lock.txt
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -e . --no-deps
if errorlevel 1 goto error
".venv\Scripts\python.exe" scripts\setup.py
if errorlevel 1 goto error
echo Setup complete. Run start.bat
pause
exit /b 0
:error
echo Setup failed. See README.md
pause
exit /b 1
