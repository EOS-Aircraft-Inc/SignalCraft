"""Column and sheet name constants for ICD sheets.

Sheet names and column identities are defined in ``scripts/icd_sheets.py``
and re-exported here so visualizer code can import a single module.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from icd_sheets import (  # noqa: E402
    ALLOCATION_ID,
    BUS_DEFINITION,
    BUS_ID,
    BUS_TOPOLOGIES,
    COLUMN_HELP_SHEET,
    CONTROLLED_SHEETS,
    DATABUSES_SHEET,
    DOC_SHEETS,
    FUNCTIONAL_SYSTEM,
    INSTALLED_IN,
    INTERFACE_TYPE,
    INTERFACE_TYPES,
    LEADING_SHEETS,
    INTERFACING_EQUIPMENT,
    README_SHEET,
    RECEIVER,
    RECEIVER_LRUS,
    RELATED_TO,
    REPEATED_PER,
    SIGNAL_ID,
    SIGNAL_ID_REF,
    SIGNAL_NAME,
    SIGNAL_OWNER,
    SIGNALS_SHEET,
    SYSTEM_TEXTUAL_NAME,
    SYSTEM_UNIQUE_ID,
    SYSTEMS_SHEET,
    TOPOLOGY,
    TOPOLOGY_ANALOG,
    TOPOLOGY_COLORS,
    TOPOLOGY_DISCRETE,
    TOPOLOGY_POWER,
    TOPOLOGY_SHARED,
    TOPOLOGY_UNIDIRECTIONAL,
    WRITER,
    WRITER_LRU,
    formal_topology_label,
    normalize_bus_topology,
    topology_color,
)

SYSTEM_ID = SYSTEM_UNIQUE_ID  # alias: 0_Systems primary / reference key

__all__ = [
    "ALLOCATION_ID",
    "BUS_DEFINITION",
    "BUS_ID",
    "BUS_TOPOLOGIES",
    "COLUMN_HELP_SHEET",
    "CONTROLLED_SHEETS",
    "DATABUSES_SHEET",
    "DOC_SHEETS",
    "FUNCTIONAL_SYSTEM",
    "INSTALLED_IN",
    "INTERFACE_TYPE",
    "INTERFACE_TYPES",
    "LEADING_SHEETS",
    "INTERFACING_EQUIPMENT",
    "README_SHEET",
    "RECEIVER",
    "RECEIVER_LRUS",
    "RELATED_TO",
    "REPEATED_PER",
    "SIGNAL_ID",
    "SIGNAL_ID_REF",
    "SIGNAL_NAME",
    "SIGNAL_OWNER",
    "SIGNALS_SHEET",
    "SYSTEM_ID",
    "SYSTEM_TEXTUAL_NAME",
    "SYSTEM_UNIQUE_ID",
    "SYSTEMS_SHEET",
    "TOPOLOGY",
    "TOPOLOGY_ANALOG",
    "TOPOLOGY_COLORS",
    "TOPOLOGY_DISCRETE",
    "TOPOLOGY_POWER",
    "TOPOLOGY_SHARED",
    "TOPOLOGY_UNIDIRECTIONAL",
    "WRITER",
    "WRITER_LRU",
    "formal_topology_label",
    "normalize_bus_topology",
    "topology_color",
]
