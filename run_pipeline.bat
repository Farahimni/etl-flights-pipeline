@echo off
cd /d "%~dp0"
venv\Scripts\python.exe main.py >> logs\scheduler.log 2>&1