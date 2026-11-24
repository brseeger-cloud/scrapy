@echo off
rem One-time setup on Windows: double-click this file, or run setup.bat
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>nul
if errorlevel 1 (
  echo Python 3.11 or later is needed. Install it from https://www.python.org/downloads/ and run this again.
  pause
  exit /b 1
)
py -3 -m venv .venv || goto :failed
.venv\Scripts\python -m pip install --quiet --upgrade pip || goto :failed
.venv\Scripts\python -m pip install --quiet -r requirements.txt || goto :failed
echo.
.venv\Scripts\python lawaudit.py status
echo.
echo Setup done. From this folder, run steps with:  .venv\Scripts\python lawaudit.py ^<step^>
pause
exit /b 0
:failed
echo Setup failed - see the messages above.
pause
exit /b 1
