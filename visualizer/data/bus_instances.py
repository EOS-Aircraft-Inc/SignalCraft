"""Bus instance graph: every physical instance of a Bus Definition.

``10_Databuses`` names ``Sender`` and ``Receiver`` per bus instance using
instance names (``HICU-3``, ``EMC-1-2``), so a definition instantiated four
times yields four independent stars — one per physical bus with its own LRU
instances — rather than one collapsed picture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from visualizer.data.models import (
    BUS_DEFINITION,
    BUS_ID,
    BUS_NAME,
    PROTOCOL,
    RECEIVER,
    SENDER,
    SPEED,
    SYSTEM_TEXTUAL_NAME,
    SYSTEM_UNIQUE_ID,
    TOPOLOGY,
    split_refs,
)

ROLE_WRITER = "writer"
ROLE_RECEIVER = "receiver"
ROLE_BOTH = "both"
ROLE_BUS = "bus"

BUS_ROLE_COLORS = {
    ROLE_WRITER: "#2980b9",  # blue
    ROLE_RECEIVER: "#c0392b",  # red
    ROLE_BOTH: "#9467bd",  # purple — writes and receives
    ROLE_BUS: "#7f8c9a",  # neutral
}

BUS_ROLE_LABELS = {
    ROLE_WRITER: "Sender",
    ROLE_RECEIVER: "Receiver",
    ROLE_BOTH: "Sender + Receiver",
    ROLE_BUS: "Bus instance",
}

DIRECTION_TO_BUS = "to_bus"
DIRECTION_FROM_BUS = "from_bus"
DIRECTION_BOTH = "both"

_INSTANCE_SUFFIX = re.compile(r"(-\d+)+$")
_BLOCK_GAP = 1.0


@dataclass
class BusInstanceGraph:
    """Positioned nodes and edges for one Bus Definition's instances."""

    nodes: pd.DataFrame
    edges: pd.DataFrame
    instances: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.nodes.empty


def _clean(value: object) -> str:
    return str(value or "").strip()


def base_system_id(instance_name: str) -> str:
    """``EMC-1-2`` -> ``EMC``: drop the ordinals appended per containment level."""
    return _INSTANCE_SUFFIX.sub("", instance_name)


def _definition_column(buses: pd.DataFrame) -> str:
    return BUS_DEFINITION if BUS_DEFINITION in buses.columns else ""


def build_bus_instance_graph(
    buses: pd.DataFrame, definition: str, systems: pd.DataFrame | None = None
) -> BusInstanceGraph:
    """One star per instance of ``definition``: its LRUs, colored by role."""
    column = _definition_column(buses)
    target = _clean(definition)
    if buses.empty or not column or not target:
        return BusInstanceGraph(pd.DataFrame(), pd.DataFrame())

    matching = buses[buses[column].astype(str).str.strip() == target]
    if matching.empty:
        return BusInstanceGraph(pd.DataFrame(), pd.DataFrame())

    names: dict[str, str] = {}
    if systems is not None and not systems.empty and SYSTEM_UNIQUE_ID in systems.columns:
        name_column = (
            SYSTEM_TEXTUAL_NAME if SYSTEM_TEXTUAL_NAME in systems.columns else SYSTEM_UNIQUE_ID
        )
        names = {
            _clean(row[SYSTEM_UNIQUE_ID]): _clean(row[name_column])
            for _, row in systems.iterrows()
        }

    nodes: list[dict] = []
    edges: list[dict] = []
    instances: list[str] = []
    cursor = 0.0

    for _, bus in matching.iterrows():
        bus_id = _clean(bus.get(BUS_ID)) or _clean(bus.get(BUS_NAME)) or target
        instances.append(bus_id)
        writers = set(split_refs(bus.get(SENDER)))
        receivers = set(split_refs(bus.get(RECEIVER)))
        dual = sorted(writers & receivers)
        # Split the dual-role LRUs across both sides: on a shared bus every node
        # is dual-role, and stacking them all on one side reads as a fan, not a bus.
        left = [(lru, ROLE_WRITER) for lru in sorted(writers - receivers)]
        left += [(lru, ROLE_BOTH) for lru in dual[::2]]
        right = [(lru, ROLE_RECEIVER) for lru in sorted(receivers - writers)]
        right += [(lru, ROLE_BOTH) for lru in dual[1::2]]

        rows = max(len(left), len(right), 1)
        bus_node = f"{bus_id}::bus"
        nodes.append(
            {
                "node_id": bus_node,
                "label": bus_id,
                "role": ROLE_BUS,
                "x": 1.0,
                "y": cursor - (rows - 1) / 2,
                "text_position": "top center",
                "hover": "<br>".join(
                    part
                    for part in [
                        bus_id,
                        _clean(bus.get(BUS_NAME)),
                        " · ".join(
                            value
                            for value in [
                                _clean(bus.get(PROTOCOL)),
                                _clean(bus.get(SPEED)),
                                _clean(bus.get(TOPOLOGY)),
                            ]
                            if value
                        ),
                        f"{len(writers)} sender(s) · {len(receivers)} receiver(s)",
                    ]
                    if part
                ),
            }
        )

        for column_items, x, text_position in (
            (left, 0.0, "middle left"),
            (right, 2.0, "middle right"),
        ):
            offset = (rows - len(column_items)) / 2
            for index, (lru, role) in enumerate(column_items):
                node_id = f"{bus_id}::{lru}"
                base = base_system_id(lru)
                title = names.get(base, "")
                nodes.append(
                    {
                        "node_id": node_id,
                        "label": lru,
                        "role": role,
                        "x": x,
                        "y": cursor - offset - index,
                        "text_position": text_position,
                        "hover": "<br>".join(
                            part
                            for part in [
                                lru,
                                title,
                                BUS_ROLE_LABELS[role],
                                f"on {bus_id}",
                            ]
                            if part
                        ),
                    }
                )
                edges.append(
                    {
                        "lru": node_id,
                        "bus": bus_node,
                        "role": role,
                        "direction": {
                            ROLE_WRITER: DIRECTION_TO_BUS,
                            ROLE_RECEIVER: DIRECTION_FROM_BUS,
                            ROLE_BOTH: DIRECTION_BOTH,
                        }[role],
                    }
                )

        cursor -= rows + _BLOCK_GAP

    return BusInstanceGraph(pd.DataFrame(nodes), pd.DataFrame(edges), instances)
