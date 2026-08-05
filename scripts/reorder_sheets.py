"""Renumber the CSV working set so the file prefixes match the reading order."""

from __future__ import annotations

import argparse
from pathlib import Path

from icd_csv import load_manifest, safe_filename, save_manifest
from icd_paths import DEFAULT_CSV_DIR
from icd_sheets import LEADING_SHEETS


def run(csv_dir: Path) -> None:
    manifest = load_manifest(csv_dir)
    by_name = {str(entry["sheet_name"]): entry for entry in manifest["sheets"]}
    leading = list(LEADING_SHEETS)

    ordered = [by_name[name] for name in leading if name in by_name]
    ordered += [
        entry
        for entry in sorted(manifest["sheets"], key=lambda e: int(e["order"]))
        if str(entry["sheet_name"]) not in set(leading)
    ]

    plan: list[tuple[Path, Path, dict]] = []
    for index, entry in enumerate(ordered, start=1):
        name = str(entry["sheet_name"])
        old = csv_dir / str(entry["csv_file"])
        new_name = f"{index:02d}_{safe_filename(name)}.csv"
        plan.append((old, csv_dir / new_name, entry))
        entry["order"] = index
        entry["csv_file"] = new_name

    # Stage through temporary names so a swap cannot overwrite a pending file.
    for old, _, _ in plan:
        if old.is_file():
            old.rename(old.with_suffix(".csv.tmp"))
    for old, new, _ in plan:
        staged = old.with_suffix(".csv.tmp")
        if staged.is_file():
            staged.rename(new)

    manifest["sheets"] = ordered
    save_manifest(manifest, csv_dir)
    for _, new, entry in plan:
        print(f"{entry['order']:02d} {entry['sheet_name']} -> {new.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_CSV_DIR)
    args = parser.parse_args()
    run(args.csv_dir.resolve())


if __name__ == "__main__":
    main()
