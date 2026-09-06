@echo off
REM Build SmartEnergyAssistant.exe (single-file, windowed).
REM See docs/WINDOWS_PACKAGING.md for details.
cd /d "%~dp0\.."
python scripts\build_windows.py
pause