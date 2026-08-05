"""Apply SignalCraft edit documents to the csv/ working set.

Usage::

    uv run python scripts/icd_edit.py --json path/to/edit.json
    uv run python scripts/icd_edit.py --json path/to/edit.json --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from icd_edit_lib import format_result, load_document, run_edit
from icd_paths import DEFAULT_CSV_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply a blind ICD edit JSON document (upsert/delete/rewrite)."
    )
    parser.add_argument(
        "--json",
        required=True,
        type=Path,
        help="Path to the edit document",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=DEFAULT_CSV_DIR,
        help="CSV working set directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the plan without writing",
    )
    args = parser.parse_args(argv)

    document = load_document(args.json)
    result = run_edit(document, csv_dir=args.csv_dir, dry_run=args.dry_run)
    print(format_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
