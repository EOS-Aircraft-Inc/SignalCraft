"""SignalCraft Streamlit visualizer.

Importing this package puts ``scripts/`` on ``sys.path`` so the shared ICD
modules (``icd_sheets``, ``icd_csv``, ``icd_edit_lib``, …) can be imported by
name. Doing it here once means no visualizer module needs its own path
bootstrap, and imports stay at the top of every file.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
