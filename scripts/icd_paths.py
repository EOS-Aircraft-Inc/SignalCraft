"""Shared paths for SignalCraft tooling."""

from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPTS_DIR.parent
DEFAULT_WORKBOOK = PROJECT_DIR / "ICD_Database.xlsx"
DEFAULT_CSV_DIR = PROJECT_DIR / "csv"
DEFAULT_REBUILT = PROJECT_DIR / "ICD_Database_rebuilt.xlsx"
MANIFEST_NAME = "_workbook_manifest.json"
