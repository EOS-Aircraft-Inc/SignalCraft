"""Instance helpers derived from the 0_Systems containment tree.

The workbook stores parameter definitions only; instances are never stored. Each
system row declares how many of itself exist per parent instance
(`Multiplicity`) and which token it contributes to the instance path
(`Instance Token`). Everything else follows from walking the tree:

- aircraft totals are the product of multiplicity up the containment chain;
- the dimensions a parameter is indexed by are the levels of its containment
  chain holding more than one instance per parent;
- a singleton (multiplicity 1) adds no index and no token.

A parameter row therefore never spells out how many instances exist. It names
dimensions (`NAC`, `NAC;EM`) and the count is read here, so changing four
nacelles to six is a single edit in 0_Systems.
"""

from __future__ import annotations

import re
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
_COUNTER = re.compile(r"\{(n+)\}")


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
        """Instance tokens contributed by this level alone."""
        row = self.rows.get(acronym)
        if row is None:
            return []
        token = (row.get("Instance Token") or "").strip()
        if not token:
            return []
        match = _COUNTER.search(token)
        if not match:
            return [part.strip() for part in token.split(";") if part.strip()]
        width = len(match.group(1))
        count = self.multiplicity(acronym)
        return [
            _COUNTER.sub(f"{index:0{width}d}", token) for index in range(1, count + 1)
        ]

    def instance_tokens(self, acronym: str) -> list[str]:
        """Exhaustive endpoint tokens for ``acronym`` (e.g. ``GBX-1..4``, ``EMC-1-1``).

        Mirrors the Sender/Receiver naming used on ``10_Databuses``:

        - own Multiplicity > 1 with an Instance Token → expand that pattern, and
          when ancestors also multiply, prefix ancestor indices
          (``EMC-1-1`` = nacelle 1, motor 1);
        - own Multiplicity == 1 under multiplied ancestors → ``UniqueId-1..N``
          (``HICU-1``, ``GBX-1``, …);
        - no multiplied ancestors → bare ``UniqueId``.
        """
        acronym = (acronym or "").strip()
        if not acronym or acronym not in self.rows:
            return [acronym] if acronym else []

        # Ancestor multiplicities > 1, outermost first (excluding self).
        ancestor_counts: list[int] = []
        for node in reversed(self.chain(acronym)):
            if node == acronym:
                break
            mult = self.multiplicity(node)
            if mult > 1:
                ancestor_counts.append(mult)

        own_mult = self.multiplicity(acronym)
        own_tokens = self.tokens(acronym)

        if own_mult > 1 and own_tokens:
            # Local indices from the Instance Token (EM-1, EM-2, …).
            local_suffixes = [
                tok[len(acronym) + 1 :] if tok.startswith(f"{acronym}-") else tok
                for tok in own_tokens
            ]
            if not ancestor_counts:
                return list(own_tokens)
            result: list[str] = []
            for idxs in product(*[range(1, n + 1) for n in ancestor_counts]):
                prefix = "-".join(str(i) for i in idxs)
                for suffix in local_suffixes:
                    result.append(f"{acronym}-{prefix}-{suffix}")
            return result

        if ancestor_counts:
            return [
                f"{acronym}-" + "-".join(str(i) for i in idxs)
                for idxs in product(*[range(1, n + 1) for n in ancestor_counts])
            ]

        return [acronym]

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
