@echo off
title RTM Bot Runner
echo ===================================================
echo Memulai RTM Bot dalam virtual environment (.venv)...
echo ===================================================
call .venv\Scripts\activate.bat
python main.py
pause
