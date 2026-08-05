"""Bridge from Streamlit Edit data to icd_edit_lib."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _PROJECT_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from icd_edit_lib import EditResult, format_result, run_edit  # noqa: E402
from icd_paths import DEFAULT_CSV_DIR  # noqa: E402


def apply_document(document: dict[str, Any], *, dry_run: bool = True) -> EditResult:
    return run_edit(document, csv_dir=DEFAULT_CSV_DIR, dry_run=dry_run)


def document_json(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False)


def sparse_upsert(
    sheet: str,
    row_id_field: str,
    row_id: str,
    original: dict[str, Any],
    edited: dict[str, Any],
) -> dict[str, Any] | None:
    """Return an upsert row with only changed fields (+ primary key), or None."""
    patch: dict[str, Any] = {}
    for key, new_val in edited.items():
        if new_val is None:
            continue
        new_s = new_val if isinstance(new_val, str) else str(new_val)
        old_s = str(original.get(key, "") or "")
        if new_s != old_s:
            patch[key] = new_s
    if not patch:
        return None
    if row_id:
        patch[row_id_field] = row_id
    return patch


__all__ = [
    "EditResult",
    "apply_document",
    "document_json",
    "format_result",
    "sparse_upsert",
]
