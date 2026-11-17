@echo off
cd /d "%~dp0"
py -3 launch.py
if errorlevel 1 (
  echo Install Python 3.12 or later, then run: py -3 -m pip install -r requirements.txt
  pause
)
