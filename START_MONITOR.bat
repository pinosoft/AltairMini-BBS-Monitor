@echo off
setlocal
cd /d "%~dp0"
title AltairMini BBS Monitor - Mystic Edition
where py >nul 2>nul
if not errorlevel 1 (
  py -3 run_monitor.py
  if not errorlevel 1 goto end
  echo.
  echo Python launcher found, but Python 3 could not run the monitor.
  echo Trying python.exe...
)
where python >nul 2>nul
if not errorlevel 1 (
  python run_monitor.py
  goto end
)
echo.
echo ERROR: Python was not found on this PC.
echo Install Python, then run START_MONITOR.bat again.
echo For Windows 7, use Python 3.8.10; newer Windows can use a current Python 3 release.
echo During installation on Windows, enable "Add Python to PATH" if offered.
echo.
pause
:end
if errorlevel 1 pause
endlocal
