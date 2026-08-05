"""Column and sheet name constants for ICD sheets.

Sheet names are defined in ``scripts/icd_sheets.py`` and re-exported here so
visualizer code can import a single module.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from icd_sheets import (  # noqa: E402
    CONTROLLED_SHEETS,
    DATABUSES_SHEET,
    LEADING_SHEETS,
    README_SHEET,
    SIGNALS_SHEET,
    SYSTEMS_SHEET,
    BUS_TOPOLOGIES,
    INTERFACE_TYPES,
    TOPOLOGY_COLORS,
    normalize_bus_topology,
    topology_color,
    formal_topology_label,
    TOPOLOGY_ANALOG,
    TOPOLOGY_DISCRETE,
    TOPOLOGY_POWER,
    TOPOLOGY_SHARED,
    TOPOLOGY_UNIDIRECTIONAL,
)

SIGNAL_ID = "Signal Id"
ALLOCATION_ID = "Allocation Id"
BUS_ID = "Bus Id"
SYSTEM_ID = "System Id"

__all__ = [
    "ALLOCATION_ID",
    "BUS_ID",
    "BUS_TOPOLOGIES",
    "CONTROLLED_SHEETS",
    "DATABUSES_SHEET",
    "INTERFACE_TYPES",
    "LEADING_SHEETS",
    "README_SHEET",
    "SIGNAL_ID",
    "SIGNALS_SHEET",
    "SYSTEM_ID",
    "SYSTEMS_SHEET",
    "TOPOLOGY_ANALOG",
    "TOPOLOGY_COLORS",
    "TOPOLOGY_DISCRETE",
    "TOPOLOGY_POWER",
    "TOPOLOGY_SHARED",
    "TOPOLOGY_UNIDIRECTIONAL",
    "formal_topology_label",
    "normalize_bus_topology",
    "topology_color",
]
