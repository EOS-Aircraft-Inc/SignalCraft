@echo off
setlocal
cd /d "%~dp0"
uv run python ".\scripts\excel_to_csv.py" %*
exit /b %ERRORLEVEL%
