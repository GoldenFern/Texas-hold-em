@echo off
title Texas Holdem Poker Server

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] .venv activation failed — run "python -m venv .venv" first
    pause
    exit /b 1
)

echo.
echo Starting server at http://localhost:5000
echo Press Ctrl+C to stop
echo.

python main.py

pause
