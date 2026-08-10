"""Canonical ICD sheet-name and controlled-vocabulary constants.

Single source of truth for controlled-sheet identifiers and formal field values
used by scripts and the visualizer. Prefer these over string literals.
"""

from __future__ import annotations

README_SHEET = "README"
COLUMN_HELP_SHEET = "Column_Help"
SYSTEMS_SHEET = "0_Systems"
SIGNALS_SHEET = "1_Signals"
DATABUSES_SHEET = "10_Databuses"

# Primary keys / identity columns.
SYSTEM_UNIQUE_ID = "UniqueId"
SIGNAL_ID = "Signal Id"
BUS_ID = "Bus Id"
ALLOCATION_ID = "Allocation Id"
DATA_ID = "Data Id"  # legacy payload key; prefer ALLOCATION_ID

# Common display / cross-reference columns.
SYSTEM_TEXTUAL_NAME = "Textual Name"
SIGNAL_NAME = "Signal Name"
INSTALLED_IN = "Installed In/Part of"
FUNCTIONAL_SYSTEM = "Functional system"
PHYSICAL_SYSTEM = "Physical System"
SIGNAL_OWNER = "Signal Owner"
REPEATED_PER = "Repeated Per"
RELATED_TO = "Related to"
INTERFACE_TYPE = "Interface Type"
BUS_DEFINITION = "Bus Definition"
BUS_NAME = "name"
WRITER = "Writer"
RECEIVER = "Receiver"
TOPOLOGY = "topology"
WRITER_LRU = "writer_lru"
RECEIVER_LRUS = "receiver_lrus"
SIGNAL_ID_REF = "signal_id"  # payload column referencing SIGNAL_ID

# Non-data workbook tabs (docs / guides). Excluded from edit engine and payloads.
DOC_SHEETS = frozenset({README_SHEET, COLUMN_HELP_SHEET})

CONTROLLED_SHEETS = frozenset(
    {
        README_SHEET,
        COLUMN_HELP_SHEET,
        SYSTEMS_SHEET,
        SIGNALS_SHEET,
        DATABUSES_SHEET,
    }
)

# Contiguous leading sheets for reorder_sheets (payload tabs follow).
LEADING_SHEETS = (
    README_SHEET,
    COLUMN_HELP_SHEET,
    SYSTEMS_SHEET,
    SIGNALS_SHEET,
    DATABUSES_SHEET,
)

# Formal Interface Type values on 1_Signals.
INTERFACE_TYPES = (
    "Digital",
    "Analog",
    "Discrete",
    "Power",
)

# Formal Topology values on 10_Databuses (digital + non-digital link kinds).
BUS_TOPOLOGIES = (
    "Unidirectional",
    "Shared",
    "Analog",
    "Discrete",
    "Power",
)

# Normalized topology keys used by the topology diagram.
TOPOLOGY_UNIDIRECTIONAL = "unidirectional"
TOPOLOGY_SHARED = "shared"
TOPOLOGY_ANALOG = "analog"
TOPOLOGY_DISCRETE = "discrete"
TOPOLOGY_POWER = "power"

TOPOLOGY_COLORS = {
    TOPOLOGY_POWER: "#c0392b",  # red — power supply
    TOPOLOGY_ANALOG: "#8B4513",  # brown — analog
    TOPOLOGY_DISCRETE: "#e67e22",  # orange — discrete
    TOPOLOGY_UNIDIRECTIONAL: "#2980b9",  # blue — mono digital
    TOPOLOGY_SHARED: "#9467bd",  # purple — shared / bidirectional digital
}

_TOPOLOGY_ALIASES = {
    "unidirectional": TOPOLOGY_UNIDIRECTIONAL,
    "uni": TOPOLOGY_UNIDIRECTIONAL,
    "mono": TOPOLOGY_UNIDIRECTIONAL,
    "monodirectional": TOPOLOGY_UNIDIRECTIONAL,
    "shared": TOPOLOGY_SHARED,
    "full duplex": TOPOLOGY_SHARED,
    "fullduplex": TOPOLOGY_SHARED,
    "duplex": TOPOLOGY_SHARED,
    "bidirectional": TOPOLOGY_SHARED,
    "analog": TOPOLOGY_ANALOG,
    "discrete": TOPOLOGY_DISCRETE,
    "power": TOPOLOGY_POWER,
    "power supply": TOPOLOGY_POWER,
}


def normalize_bus_topology(value: object) -> str:
    """Map free-text Topology / Interface Type to a diagram topology key."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in _TOPOLOGY_ALIASES:
        return _TOPOLOGY_ALIASES[text]
    for alias, key in _TOPOLOGY_ALIASES.items():
        if alias in text:
            return key
    return ""


def topology_color(value: object, *, default: str = "#6c757d") -> str:
    """Return the diagram color for a Topology / bus_mode / Interface Type."""
    key = normalize_bus_topology(value)
    return TOPOLOGY_COLORS.get(key, default)


def formal_topology_label(value: object) -> str:
    """Canonical display label for a topology key (Unidirectional, Shared, …)."""
    key = normalize_bus_topology(value)
    mapping = {
        TOPOLOGY_UNIDIRECTIONAL: "Unidirectional",
        TOPOLOGY_SHARED: "Shared",
        TOPOLOGY_ANALOG: "Analog",
        TOPOLOGY_DISCRETE: "Discrete",
        TOPOLOGY_POWER: "Power",
    }
    return mapping.get(key, str(value or "").strip())
