@echo off
title Texas Holdem Poker Server

call D:\Software\Anaconda\Scripts\activate.bat base
if errorlevel 1 (
    echo [ERROR] Conda env activation failed
    pause
    exit /b 1
)

echo.
echo Starting server at http://localhost:5000
echo Press Ctrl+C to stop
echo.

python main.py

pause