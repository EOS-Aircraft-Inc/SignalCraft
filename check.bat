@echo off
setlocal
cd /d "%~dp0"

echo.
echo === Checking the code (ruff) ===
uv run ruff check .
if errorlevel 1 goto :failed

echo.
echo === Running the tests (pytest) ===
uv run pytest -q
if errorlevel 1 goto :failed

echo.
echo === Checking the database (integrity check) ===
uv run python ".\scripts\database_integrity_check.py" --quiet-warnings
if errorlevel 1 goto :failed

echo.
echo All checks passed.
exit /b 0

:failed
echo.
echo Something above failed - read the message and fix it before committing.
exit /b 1
