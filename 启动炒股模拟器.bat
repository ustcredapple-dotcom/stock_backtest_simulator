@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 stock_server.py
) else (
  python stock_server.py
)
pause
