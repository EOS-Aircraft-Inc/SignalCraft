"""A few checks on the code that writes the database.

Deliberately short. This does **not** try to cover everything — it covers the
handful of rules that, if they broke, would quietly corrupt `csv/`:

1. an edit that breaks a rule is refused, and nothing is written;
2. ids stay unique, inside a tab and across the whole workbook;
3. a normal edit still goes through and changes only what was asked.

If you add a rule to the edit engine and it matters that much, add one case to
`REFUSED` or `ACCEPTED` below. If it does not, leave this file alone — a test
nobody understands is worse than no test.

Every test runs against a throwaway copy of `csv/`, so the real database is
never touched.

Run from the repo root::

    uv run pytest
"""

from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from icd_csv import csv_path_for_sheet  # noqa: E402
from icd_edit_lib import run_edit  # noqa: E402

# Rows that exist in the shipped database, used as fixtures below.
A_SIGNAL = "SIG-001"
A_SYSTEM = "FCC"
AN_ALLOCATION = "DBUS-ICM-002"  # lives on the ICM_FCS tab
AN_ALLOCATION_ELSEWHERE = "DBUS-001"  # lives on the IRU_TX tab


@pytest.fixture
def csv_dir(tmp_path: Path) -> Path:
    """A private copy of the database, thrown away after each test."""
    work = tmp_path / "csv"
    work.mkdir()
    for item in (PROJECT_ROOT / "csv").iterdir():
        if item.is_file():
            shutil.copy(item, work / item.name)
    return work


def rows_at(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def rows(csv_dir: Path, sheet: str) -> list[dict[str, str]]:
    """Rows of a sheet, resolved through the manifest so renumbering the
    CSV files (they are prefixed by sheet order) cannot break these tests."""
    return rows_at(csv_path_for_sheet(sheet, csv_dir))


REFUSED = [
    (
        "an allocation id already used on another tab",
        {
            "upsert": {
                "ICM_FCS": [
                    {
                        "Allocation Id": AN_ALLOCATION_ELSEWHERE,
                        "Data name": "clash",
                        "Signal Id": A_SIGNAL,
                    }
                ]
            }
        },
    ),
    (
        "renaming a signal onto one that already exists",
        {"rewrite": {"ids": [{"from": "SIG-010", "to": "SIG-011"}]}},
    ),
    (
        "pointing an allocation at a signal that does not exist",
        {"upsert": {"ICM_FCS": [{"Allocation Id": AN_ALLOCATION, "Signal Id": "SIG-9999"}]}},
    ),
    (
        "naming a system that does not exist",
        {"upsert": {"1_Signals": [{"Signal Id": A_SIGNAL, "Signal Owner": "NOPE"}]}},
    ),
    (
        "giving the aircraft row a multiplicity it may not have",
        {"upsert": {"0_Systems": [{"UniqueId": "AC", "Multiplicity": "3"}]}},
    ),
]

ACCEPTED = [
    (
        "editing a field on an existing allocation",
        {"upsert": {"ICM_FCS": [{"Allocation Id": AN_ALLOCATION, "Notes": "fine"}]}},
    ),
    (
        "adding an allocation and letting the id be allocated",
        {"upsert": {"ICM_FCS": [{"Data name": "new row", "Signal Id": A_SIGNAL}]}},
    ),
    (
        "adding a signal and letting the id be allocated",
        {"upsert": {"1_Signals": [{"Signal Name": "new", "Signal Owner": A_SYSTEM}]}},
    ),
    (
        "moving an id to a tab after deleting it from the old one",
        {
            "delete": {"IRU_TX": [AN_ALLOCATION_ELSEWHERE]},
            "upsert": {
                "ICM_FCS": [
                    {
                        "Allocation Id": AN_ALLOCATION_ELSEWHERE,
                        "Data name": "moved",
                        "Signal Id": A_SIGNAL,
                    }
                ]
            },
        },
    ),
]


@pytest.mark.parametrize("what,document", REFUSED, ids=[c[0] for c in REFUSED])
def test_a_broken_edit_is_refused(what: str, document: dict, csv_dir: Path) -> None:
    result = run_edit(document, csv_dir=csv_dir)
    assert not result.ok, f"{what} should have been refused"
    assert result.errors, "a refusal must say why"


@pytest.mark.parametrize("what,document", ACCEPTED, ids=[c[0] for c in ACCEPTED])
def test_a_valid_edit_goes_through(what: str, document: dict, csv_dir: Path) -> None:
    result = run_edit(document, csv_dir=csv_dir)
    assert result.ok, f"{what} should have been accepted: {result.errors}"


def test_a_refused_edit_writes_nothing(csv_dir: Path) -> None:
    """The important half of a refusal: the database is left alone."""
    before = rows(csv_dir, "ICM_FCS")
    run_edit(
        {
            "upsert": {
                "ICM_FCS": [
                    {
                        "Allocation Id": AN_ALLOCATION_ELSEWHERE,
                        "Data name": "clash",
                        "Signal Id": A_SIGNAL,
                    }
                ]
            }
        },
        csv_dir=csv_dir,
    )
    assert rows(csv_dir, "ICM_FCS") == before


def test_an_edit_changes_only_what_was_asked(csv_dir: Path) -> None:
    """Fields left out of the document keep their stored value."""
    before = {r["Allocation Id"]: r for r in rows(csv_dir, "ICM_FCS")}
    result = run_edit(
        {"upsert": {"ICM_FCS": [{"Allocation Id": AN_ALLOCATION, "Notes": "only this"}]}},
        csv_dir=csv_dir,
    )
    assert result.ok, result.errors

    after = {r["Allocation Id"]: r for r in rows(csv_dir, "ICM_FCS")}
    assert set(after) == set(before), "no row should appear or disappear"
    changed = {
        column
        for column, value in after[AN_ALLOCATION].items()
        if before[AN_ALLOCATION][column] != value
    }
    assert changed == {"Notes"}


def test_new_allocation_ids_are_unique_across_every_tab(csv_dir: Path) -> None:
    """Ids are handed out against the whole workbook, not one tab."""
    result = run_edit(
        {
            "upsert": {
                "ICM_FCS": [{"Data name": "a", "Signal Id": A_SIGNAL}],
                "IRU_TX": [{"Data name": "b", "Signal Id": A_SIGNAL}],
            }
        },
        csv_dir=csv_dir,
    )
    assert result.ok, result.errors

    seen: list[str] = []
    for path in sorted(csv_dir.glob("*.csv")):
        for row in rows_at(path):
            if row.get("Allocation Id"):
                seen.append(row["Allocation Id"])
    duplicates = {value for value in seen if seen.count(value) > 1}
    assert not duplicates, f"the same allocation id appears twice: {duplicates}"
