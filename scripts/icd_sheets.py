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

# Common display / cross-reference columns.
SYSTEM_TEXTUAL_NAME = "Textual Name"
SIGNAL_NAME = "Signal Name"
INSTALLED_IN = "Installed In/Part of"
DOMAIN = "Domain"
INTERFACING_EQUIPMENT = "Interfacing Equipment"
SIGNAL_OWNER = "Signal Owner"
REPEATED_PER = "Repeated Per"
# Signal-to-signal links on 1_Signals, both holding Signal Ids. COMPUTED_FROM
# names the signals this value is produced from; SAME_QUANTITY_AS declares
# that the rows observe one and the same real-world quantity. Anything a
# reader could derive from the allocations, the messages or the topology map
# is not recorded here.
COMPUTED_FROM = "Computed from"
SAME_QUANTITY_AS = "Same quantity as"
INTERFACE_TYPE = "Interface Type"
BUS_DEFINITION = "Bus Definition"
BUS_NAME = "Bus name"
BUS_DESCRIPTION = "Bus description"
PROTOCOL = "Protocol"
SPEED = "Speed"
TOPOLOGY = "Topology"

# Endpoint columns. 10_Databuses names bus-instance nodes, the bus-definition
# tabs name the endpoints of one allocation; both use the same column names.
SENDER = "Sender"
RECEIVER = "Receiver"

# Bus-definition tab columns.
DATA_NAME = "Data name"
INSTANCE_DIMENSION = "Instance dimension"
MESSAGE_ID = "Message ID"
LABEL = "Label"
START_BIT = "Start bit"
STOP_BIT = "Stop bit"
ENCODING = "Encoding"
SCALE = "Scale"
RESOLUTION = "Resolution"
MINIMUM = "Minimum"
MAXIMUM = "Maximum"
# Named for the quantity it holds: a period in milliseconds, not a frequency.
REFRESH_PERIOD_MS = "Refresh period (ms)"
VALIDITY = "Validity"

# Shared by several sheets.
UNIT = "Unit"
NOTES = "Notes"
DESCRIPTION = "Description"

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

# Formal Type values on 0_Systems. A Type=Domain row declares a domain, which
# other rows then reference from their Domain column.
SYSTEM_TYPES = (
    "Aircraft",
    "Domain",
    "Zone",
    "Component",
)

# Aircraft / Domain rows are hierarchy or functional labels, never instantiated:
# Multiplicity stays empty (a literal "1" is tolerated) and there is no token.
NO_INSTANCE_SYSTEM_TYPES = frozenset({"Aircraft", "Domain"})

# Zone / Component are real equipment and are counted per parent.
INSTANTIATED_SYSTEM_TYPES = frozenset({"Zone", "Component"})


def normalize_system_type(value: object) -> str:
    """Match a 0_Systems Type to its formal spelling, ignoring case."""
    text = str(value or "").strip()
    for formal in SYSTEM_TYPES:
        if text.lower() == formal.lower():
            return formal
    return text


def system_multiplicity_error(
    system_type: object,
    multiplicity: object,
) -> str | None:
    """Explain why Multiplicity does not suit this Type, else None.

    One rule shared by the integrity check, the edit engine preflight and the
    System list editor, so all three agree:

    - Aircraft / Domain: Multiplicity empty or "1".
    - Zone / Component: Multiplicity is a positive integer, the count per
      parent instance. Instance names follow from it (``UniqueId-1..N``).
    - Any other (or empty) Type is not judged here.
    """
    typ = normalize_system_type(system_type)
    mult = str(multiplicity or "").strip()

    if typ in NO_INSTANCE_SYSTEM_TYPES:
        if mult and mult != "1":
            return (
                f"Type '{typ}' is a label, not equipment: Multiplicity must be "
                f"empty or '1' (got {mult or 'empty'!r})."
            )
        return None

    if typ in INSTANTIATED_SYSTEM_TYPES and (not mult.isdigit() or int(mult) < 1):
        return (
            f"Type '{typ}' requires Multiplicity as a positive integer, the "
            f"count per parent instance (got {mult or 'empty'!r})."
        )
    return None


# Formal Signal Role values on 1_Signals, in reading order.
SIGNAL_ROLES = (
    "Measurement",
    "Command",
    "Request",
    "Computed",
    "Power",
)

# Direction of the physical interface implied by a role. Measurement flows from
# the Interfacing Equipment to the Owner; Command and Power flow the other way.
# Request and Computed are digital and have no hardwired leg of their own.
ROLES_TOWARD_OWNER = frozenset({"Measurement"})
ROLES_FROM_OWNER = frozenset({"Command", "Power"})

# Roles a bus allocation drives away from its owner (adds Request, which is a
# bus message rather than a hardwired drive).
BUS_ROLES_FROM_OWNER = frozenset({"Command", "Request", "Power"})


# Formal Interface Type values on 1_Signals. Power is split by network: the
# low-voltage supply (28 V) and the high-voltage traction network (800 V) are
# separate physical networks and are filtered separately on the topology map.
INTERFACE_TYPES = (
    "Digital",
    "Analog",
    "Discrete",
    "Low Power",
    "High Power",
)

# Formal Topology values on 10_Databuses (digital + non-digital link kinds).
BUS_TOPOLOGIES = (
    "Unidirectional",
    "Shared",
    "Analog",
    "Discrete",
    "Low Power",
    "High Power",
)

# Normalized topology keys used by the topology diagram.
TOPOLOGY_UNIDIRECTIONAL = "unidirectional"
TOPOLOGY_SHARED = "shared"
TOPOLOGY_ANALOG = "analog"
TOPOLOGY_DISCRETE = "discrete"
TOPOLOGY_LOW_POWER = "low_power"
TOPOLOGY_HIGH_POWER = "high_power"

# Callers re-normalize values that are already keys, so a key must map to
# itself. Single-word keys did so by accident; low_power / high_power do not.
TOPOLOGY_KEYS = frozenset(
    {
        TOPOLOGY_UNIDIRECTIONAL,
        TOPOLOGY_SHARED,
        TOPOLOGY_ANALOG,
        TOPOLOGY_DISCRETE,
        TOPOLOGY_LOW_POWER,
        TOPOLOGY_HIGH_POWER,
    }
)

TOPOLOGY_COLORS = {
    TOPOLOGY_LOW_POWER: "#e74c3c",  # light red — 28 V supply network
    TOPOLOGY_HIGH_POWER: "#922b21",  # dark red — 800 V traction network
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
    # No bare "power" alias: it would swallow "low power" / "high power" in the
    # substring pass, and a stale "Power" is better reported than guessed.
    "low power": TOPOLOGY_LOW_POWER,
    "low voltage": TOPOLOGY_LOW_POWER,
    "high power": TOPOLOGY_HIGH_POWER,
    "high voltage": TOPOLOGY_HIGH_POWER,
}


def normalize_bus_topology(value: object) -> str:
    """Map free-text Topology / Interface Type to a diagram topology key."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in TOPOLOGY_KEYS:
        return text
    if text in _TOPOLOGY_ALIASES:
        return _TOPOLOGY_ALIASES[text]
    # Longest alias first, so "high power bus" cannot match a shorter alias.
    for alias in sorted(_TOPOLOGY_ALIASES, key=len, reverse=True):
        if alias in text:
            return _TOPOLOGY_ALIASES[alias]
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
        TOPOLOGY_LOW_POWER: "Low Power",
        TOPOLOGY_HIGH_POWER: "High Power",
    }
    return mapping.get(key, str(value or "").strip())
