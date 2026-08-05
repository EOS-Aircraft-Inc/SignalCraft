@echo off
setlocal
cd /d "%~dp0"
uv run python ".\scripts\csv_to_excel.py" %*
exit /b %ERRORLEVEL%
