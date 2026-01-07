@echo off
echo Starting Gumbo GUM Application...
echo.
echo This will start the background tracking service and open your dashboard.
echo.
echo Press any key to continue...
pause >nul

echo.
echo Starting services...
python start_gum.py

echo.
echo If the app didn't start automatically, please run: python start_gum.py
pause

