"""Instance helpers derived from the 0_Systems containment tree.

The workbook stores parameter definitions only; instances are never stored. Each
system row declares only how many of itself exist per parent instance
(`Multiplicity`). Everything else follows from walking the tree:

- an instance name is the UniqueId plus one ordinal per multiplied level of its
  containment chain, outermost first (`EMC-1-2`);
- aircraft totals are the product of multiplicity up the containment chain;
- the dimensions a parameter is indexed by are the levels of its containment
  chain holding more than one instance per parent;
- a singleton (multiplicity 1) adds no index.

A parameter row therefore never spells out how many instances exist. It names
dimensions (`NAC`, `NAC;EM`) and the count is read here, so changing four
nacelles to six is a single edit in 0_Systems.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import product
from pathlib import Path

from icd_csv import read_sheet
from icd_paths import DEFAULT_CSV_DIR
from icd_sheets import (
    BUS_DEFINITION,
    BUS_ID,
    INSTALLED_IN,
    SYSTEM_UNIQUE_ID,
    SYSTEMS_SHEET,
)

ROOT_TOKEN = "AC"


class SystemTree:
    """Read-only view of the 0_Systems containment tree."""

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows: dict[str, dict[str, str]] = {}
        for row in rows:
            unique_id = (row.get(SYSTEM_UNIQUE_ID) or "").strip()
            if unique_id:
                self.rows[unique_id] = row

    @classmethod
    def load(cls, csv_dir: Path = DEFAULT_CSV_DIR, manifest=None) -> SystemTree:
        _, rows = read_sheet(SYSTEMS_SHEET, csv_dir, manifest)
        return cls(rows)

    @property
    def acronyms(self) -> set[str]:
        return set(self.rows)

    def parent(self, acronym: str) -> str:
        row = self.rows.get(acronym)
        if not row:
            return ""
        return (row.get(INSTALLED_IN) or "").strip()

    def multiplicity(self, acronym: str) -> int:
        row = self.rows.get(acronym)
        if row is None:
            return 0
        value = (row.get("Multiplicity") or "").strip()
        return int(value) if value.isdigit() else 0

    def chain(self, acronym: str) -> list[str]:
        """Containment chain from ``acronym`` up to the root."""
        result: list[str] = []
        node = acronym
        while node and node in self.rows and node not in result:
            result.append(node)
            node = self.parent(node)
        return result

    def tokens(self, acronym: str) -> list[str]:
        """Instance tokens contributed by this level alone (``EM-1``, ``EM-2``)."""
        count = self.multiplicity(acronym)
        if acronym not in self.rows or count <= 1:
            return []
        return [f"{acronym}-{index}" for index in range(1, count + 1)]

    def instance_tokens(self, acronym: str) -> list[str]:
        """Exhaustive endpoint tokens for ``acronym`` (e.g. ``GBX-1..4``, ``EMC-1-1``).

        Mirrors the Sender/Receiver naming used on ``10_Databuses``. An instance
        name is the UniqueId plus one ordinal per multiplied level of its
        containment chain, outermost first, so ``Multiplicity`` alone determines
        every name:

        - own Multiplicity > 1 → one ordinal of its own, after any ancestor
          ordinals (``EMC-1-1`` = nacelle 1, motor 1);
        - own Multiplicity == 1 under multiplied ancestors → ``UniqueId-1..N``
          (``HICU-1``, ``GBX-1``, …);
        - no multiplied ancestors → bare ``UniqueId``.
        """
        acronym = (acronym or "").strip()
        if not acronym or acronym not in self.rows:
            return [acronym] if acronym else []

        # Multiplied levels of the chain, outermost first, self last.
        counts: list[int] = []
        for node in reversed(self.chain(acronym)):
            mult = self.multiplicity(node)
            if mult > 1:
                counts.append(mult)

        if not counts:
            return [acronym]
        return [
            f"{acronym}-" + "-".join(str(i) for i in idxs)
            for idxs in product(*[range(1, n + 1) for n in counts])
        ]


def bus_family_name(row: Mapping[str, str]) -> str:
    """Family handle for a ``10_Databuses`` row (``Bus Definition`` preferred)."""
    return (
        str(row.get(BUS_DEFINITION) or "").strip()
        or str(row.get("definition_tab") or "").strip()
    )


def family_map(rows: Iterable[Mapping[str, str]]) -> dict[str, list[str]]:
    """Bus instances grouped by the definition they share.

    Prefers the live CSV column ``Bus Definition``; falls back to
    ``definition_tab`` (loader alias). The family name is the definition tab
    handle used for Generic topology and “all instances of this bus”.
    """
    families: dict[str, list[str]] = {}
    for row in rows:
        bus_id = str(row.get(BUS_ID) or "").strip()
        family = bus_family_name(row)
        if bus_id and family:
            families.setdefault(family, []).append(bus_id)
    return families
