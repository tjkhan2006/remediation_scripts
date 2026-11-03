@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto dependencies
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 -m venv .venv
if errorlevel 1 goto failed
goto dependencies
:usepython
python -m venv .venv
if errorlevel 1 goto failed
:dependencies
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'"
if errorlevel 1 goto failed
if exist ".venv\tag_inspector_setup_complete" goto launch
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
type nul > ".venv\tag_inspector_setup_complete"
:launch
".venv\Scripts\python.exe" pdf_tag_inspector.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Setup or launch failed. Install Python 3.11 or newer with Tcl/Tk support.
echo Python 3.12 is recommended. The first launch needs internet access.
echo If needed, remove the .venv folder and try again.
pause
exit /b 1
