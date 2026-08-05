"""CSV helpers for the ICD export folder."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from icd_paths import DEFAULT_CSV_DIR, MANIFEST_NAME


def load_manifest(csv_dir: Path = DEFAULT_CSV_DIR) -> dict[str, Any]:
    path = csv_dir / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(
            f"Manifest not found: {path}. Run excel_to_csv.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(manifest: dict[str, Any], csv_dir: Path = DEFAULT_CSV_DIR) -> None:
    path = csv_dir / MANIFEST_NAME
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sheet_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(entry["sheet_name"]): entry for entry in manifest["sheets"]}


def csv_path_for_sheet(
    sheet_name: str,
    csv_dir: Path = DEFAULT_CSV_DIR,
    manifest: dict[str, Any] | None = None,
) -> Path:
    manifest = manifest or load_manifest(csv_dir)
    entry = sheet_index(manifest).get(sheet_name)
    if entry is None:
        raise KeyError(f"Sheet not found in manifest: {sheet_name}")
    return csv_dir / str(entry["csv_file"])


def read_sheet(
    sheet_name: str,
    csv_dir: Path = DEFAULT_CSV_DIR,
    manifest: dict[str, Any] | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    path = csv_path_for_sheet(sheet_name, csv_dir, manifest)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = list(reader.fieldnames or [])
        rows = [{key: (row.get(key) or "") for key in fieldnames} for row in reader]
    return fieldnames, rows


def write_sheet(
    sheet_name: str,
    fieldnames: list[str],
    rows: list[dict[str, str]],
    csv_dir: Path = DEFAULT_CSV_DIR,
    manifest: dict[str, Any] | None = None,
) -> Path:
    path = csv_path_for_sheet(sheet_name, csv_dir, manifest)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return path


def safe_filename(sheet_name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", sheet_name).strip().rstrip(".")
    return name or "Sheet"


def next_csv_prefix(manifest: dict[str, Any]) -> int:
    orders = [int(entry["order"]) for entry in manifest["sheets"]]
    return (max(orders) if orders else 0) + 1


def ensure_sheet(
    sheet_name: str,
    fieldnames: list[str],
    csv_dir: Path = DEFAULT_CSV_DIR,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an empty CSV sheet and register it in the manifest if missing."""
    manifest = manifest or load_manifest(csv_dir)
    index = sheet_index(manifest)
    if sheet_name in index:
        return manifest

    order = next_csv_prefix(manifest)
    filename = f"{order:02d}_{safe_filename(sheet_name)}.csv"
    path = csv_dir / filename
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()

    manifest["sheets"].append(
        {
            "order": order,
            "sheet_name": sheet_name,
            "csv_file": filename,
            "sheet_state": "visible",
            "max_row": 1,
            "max_column": len(fieldnames),
        }
    )
    save_manifest(manifest, csv_dir)
    return manifest


def nonempty(row: dict[str, str], key: str) -> bool:
    return bool(str(row.get(key, "")).strip())


def collect_ids(
    rows: list[dict[str, str]],
    key: str,
) -> list[str]:
    return [str(row[key]).strip() for row in rows if nonempty(row, key)]


_ID_PATTERN = re.compile(r"^([A-Za-z]+(?:-[A-Za-z]+)*)-(\d+)$")


def next_id(existing: list[str], prefix: str, width: int | None = None) -> str:
    """Allocate the next identifier for a prefix such as SIG, SYS, or DBUS."""
    numbers: list[int] = []
    for value in existing:
        match = _ID_PATTERN.match(value)
        if match and match.group(1) == prefix:
            numbers.append(int(match.group(2)))
            if width is None:
                width = len(match.group(2))
    next_number = (max(numbers) + 1) if numbers else 1
    digits = width if width is not None else 3
    return f"{prefix}-{next_number:0{digits}d}"


def split_refs(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def join_refs(values: list[str]) -> str:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return ";".join(seen)
