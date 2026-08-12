"""Signal dataflow graph.

One graph per selected signal: the hardwired leg declared on ``1_Signals``
(Analog / Discrete / Power) plus every bus leg carried by allocations, so a
sensor-to-consumer path reads end to end instead of as a list of bus rows.

Direction comes from ``Signal Role`` (see the workbook ``Column_Help`` sheet):
Measurement flows Interfacing Equipment to Owner, Command and Power flow Owner
to Interfacing Equipment, Request and Computed are digital and have no
hardwired leg.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import pandas as pd

from visualizer.data.models import (
    ALLOCATION_ID,
    INTERFACE_TYPE,
    INTERFACING_EQUIPMENT,
    RECEIVER,
    RELATED_TO,
    REPEATED_PER,
    ROLES_FROM_OWNER,
    ROLES_TOWARD_OWNER,
    SENDER,
    SIGNAL_ID,
    SIGNAL_OWNER,
    SYSTEM_TEXTUAL_NAME,
    SYSTEM_UNIQUE_ID,
    TOPOLOGY_ANALOG,
    TOPOLOGY_DISCRETE,
    TOPOLOGY_POWER,
    TOPOLOGY_UNIDIRECTIONAL,
    split_refs,
)

SIGNAL_ROLE = "Signal Role"
CONNECTION_TYPE = "Connection Type"
PHYSICAL_ID = "Physical Id"
DEFINITION_TAB = "definition_tab"
INSTANCE_DIMENSION = "instance_dimension"

DIGITAL = "Digital"
HARDWIRED = ("Analog", "Discrete", "Power")

# Interface Type -> topology key, so dataflow colors match the Bus Topology page.
INTERFACE_TOPOLOGY = {
    DIGITAL: TOPOLOGY_UNIDIRECTIONAL,
    "Analog": TOPOLOGY_ANALOG,
    "Discrete": TOPOLOGY_DISCRETE,
    "Power": TOPOLOGY_POWER,
}


NODE_SYSTEM = "system"
NODE_SENSOR = "sensor"
NODE_EFFECTOR = "effector"

_MAX_HOVER_ITEMS = 8


@dataclass
class Dataflow:
    """Positioned dataflow graph for one signal and its merged relatives."""

    nodes: pd.DataFrame
    edges: pd.DataFrame
    signal_ids: list[str] = field(default_factory=list)
    feedback: set[tuple[str, str]] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return self.nodes.empty


def _clean(value: object) -> str:
    return str(value or "").strip()


def related_signal_ids(signals: pd.DataFrame, signal_id: str) -> list[str]:
    """The selected signal plus the relatives whose legs belong on its diagram.

    ``Related to`` is followed one step only, in both directions: the full
    transitive closure chains 54 of this database's 224 signals into a single
    blob. ``Physical Id`` is a declared equivalence class over one physical
    quantity, so it is merged whole.
    """
    sid = _clean(signal_id)
    if not sid or signals.empty or SIGNAL_ID not in signals.columns:
        return [sid] if sid else []

    ids = signals[SIGNAL_ID].astype(str).str.strip()
    row = signals.loc[ids == sid]
    found = {sid}

    if RELATED_TO in signals.columns:
        if not row.empty:
            found |= set(split_refs(row.iloc[0].get(RELATED_TO)))
        declares = signals[RELATED_TO].fillna("").astype(str).apply(lambda v: sid in split_refs(v))
        found |= set(ids[declares])

    if PHYSICAL_ID in signals.columns and not row.empty:
        phys = _clean(row.iloc[0].get(PHYSICAL_ID))
        if phys:
            same = signals[PHYSICAL_ID].fillna("").astype(str).str.strip() == phys
            found |= set(ids[same])

    return sorted((found & set(ids)) | {sid})


class _Builder:
    """Accumulates nodes and de-duplicated edges while walking the signals."""

    def __init__(self, system_names: dict[str, str]) -> None:
        self._system_names = system_names
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str, str], dict] = {}

    def system(self, unique_id: str) -> str:
        node = self.nodes.setdefault(
            unique_id,
            {
                "node_id": unique_id,
                "label": unique_id,
                "kind": NODE_SYSTEM,
                "interface": "",
                "title": self._system_names.get(unique_id, ""),
            },
        )
        return str(node["node_id"])

    def hardware(self, signal_id: str, kind: str, interface: str, label: str) -> str:
        node_id = f"{kind}::{signal_id}"
        self.nodes.setdefault(
            node_id,
            {
                "node_id": node_id,
                "label": label or interface,
                "kind": kind,
                "interface": interface,
                "title": f"{interface} {kind} of {signal_id}",
            },
        )
        return node_id

    def edge(
        self,
        source: str,
        target: str,
        interface: str,
        *,
        bus: str = "",
        allocation: str = "",
        signal: str = "",
        detail: str = "",
    ) -> None:
        if not source or not target or source == target:
            return
        entry = self.edges.setdefault(
            (source, target, interface, bus),
            {
                "source": source,
                "target": target,
                "interface": interface,
                "bus": bus,
                "allocations": [],
                "signals": set(),
                "details": set(),
            },
        )
        if allocation:
            entry["allocations"].append(allocation)
        if signal:
            entry["signals"].add(signal)
        if detail:
            entry["details"].add(detail)


def _add_hardwired_leg(builder: _Builder, row: pd.Series, signal_id: str) -> None:
    """Sensor/effector leg for a signal whose interface is not digital."""
    interface = _clean(row.get(INTERFACE_TYPE))
    role = _clean(row.get(SIGNAL_ROLE))
    owner = _clean(row.get(SIGNAL_OWNER))
    equip = _clean(row.get(INTERFACING_EQUIPMENT))
    if interface not in HARDWIRED or not owner:
        return

    detail = _clean(row.get(CONNECTION_TYPE))
    repeated = _clean(row.get(REPEATED_PER))
    if repeated:
        detail = f"{detail} · per {repeated}" if detail else f"per {repeated}"

    owner_node = builder.system(owner)
    if role in ROLES_TOWARD_OWNER:
        source = (
            builder.system(equip)
            if equip and equip != owner
            # Interfacing Equipment == Owner: the acquisition is internal, so
            # stand the sensing hardware up as its own node.
            else builder.hardware(
                signal_id, NODE_SENSOR, interface, _clean(row.get(CONNECTION_TYPE))
            )
        )
        builder.edge(source, owner_node, interface, signal=signal_id, detail=detail)
    elif role in ROLES_FROM_OWNER:
        target = (
            builder.system(equip)
            if equip and equip != owner
            else builder.hardware(
                signal_id, NODE_EFFECTOR, interface, _clean(row.get(CONNECTION_TYPE))
            )
        )
        builder.edge(owner_node, target, interface, signal=signal_id, detail=detail)


def _add_bus_legs(builder: _Builder, payload: pd.DataFrame, members: list[str]) -> None:
    """One edge per writer/receiver/bus-definition, aggregating allocations."""
    if payload.empty or SIGNAL_ID not in payload.columns:
        return
    linked = payload[
        payload[SIGNAL_ID].fillna("").astype(str).str.strip().isin(members)
    ]
    for _, alloc in linked.iterrows():
        dimension = _clean(alloc.get(INSTANCE_DIMENSION))
        for writer in split_refs(alloc.get(SENDER)):
            for receiver in split_refs(alloc.get(RECEIVER)):
                builder.edge(
                    builder.system(writer),
                    builder.system(receiver),
                    DIGITAL,
                    bus=_clean(alloc.get(DEFINITION_TAB)),
                    allocation=_clean(alloc.get(ALLOCATION_ID)),
                    signal=_clean(alloc.get(SIGNAL_ID)),
                    detail=f"per {dimension}" if dimension else "",
                )


def _layer_positions(
    node_ids: list[str], edges: list[dict]
) -> tuple[dict[str, tuple[float, float]], set[tuple[str, str]]]:
    """Left-to-right layering; edges closing a cycle are kept but not layered."""
    graph = nx.DiGraph()
    graph.add_nodes_from(node_ids)
    for edge in edges:
        graph.add_edge(edge["source"], edge["target"])

    feedback: set[tuple[str, str]] = set()
    dag = nx.DiGraph(graph)
    while True:
        try:
            cycle = nx.find_cycle(dag, orientation="original")
        except nx.NetworkXNoCycle:
            break
        source, target = cycle[-1][0], cycle[-1][1]
        dag.remove_edge(source, target)
        feedback.add((source, target))

    positions: dict[str, tuple[float, float]] = {}
    placed: dict[str, float] = {}
    for depth, layer in enumerate(nx.topological_generations(dag)):

        def barycenter(node: str) -> float:
            upstream = [placed[p] for p in dag.predecessors(node) if p in placed]
            return sum(upstream) / len(upstream) if upstream else 0.0

        ordered = sorted(layer, key=lambda node: (barycenter(node), node))
        for index, node in enumerate(ordered):
            offset = (len(ordered) - 1) / 2 - index
            positions[node] = (float(depth), offset)
            placed[node] = offset
    return positions, feedback


def _edge_label(entry: dict) -> str:
    if entry["bus"]:
        count = len(entry["allocations"])
        return f"{entry['bus']} ×{count}" if count > 1 else entry["bus"]
    return entry["interface"]


def _edge_hover(entry: dict, selected: str) -> str:
    lines = [f"{entry['source']} → {entry['target']}", entry["interface"]]
    if entry["bus"]:
        lines.append(f"bus definition: {entry['bus']}")
    allocations = entry["allocations"]
    if allocations:
        shown = ", ".join(sorted(allocations)[:_MAX_HOVER_ITEMS])
        if len(allocations) > _MAX_HOVER_ITEMS:
            shown += f", … (+{len(allocations) - _MAX_HOVER_ITEMS})"
        lines.append(f"{len(allocations)} allocation(s): {shown}")
    lines.extend(sorted(entry["details"]))
    others = sorted(entry["signals"] - {selected})
    if others:
        lines.append(f"via related: {', '.join(others)}")
    return "<br>".join(lines)


def build_dataflow(bundle, signal_id: str) -> Dataflow:
    """Positioned dataflow for ``signal_id`` merged with its declared relatives."""
    sid = _clean(signal_id)
    signals = bundle.signals
    members = related_signal_ids(signals, sid)
    if not members or signals.empty or SIGNAL_ID not in signals.columns:
        return Dataflow(pd.DataFrame(), pd.DataFrame(), members)

    system_names: dict[str, str] = {}
    systems = bundle.systems
    if not systems.empty and SYSTEM_UNIQUE_ID in systems.columns:
        name_col = (
            SYSTEM_TEXTUAL_NAME if SYSTEM_TEXTUAL_NAME in systems.columns else SYSTEM_UNIQUE_ID
        )
        system_names = {
            _clean(r[SYSTEM_UNIQUE_ID]): _clean(r[name_col]) for _, r in systems.iterrows()
        }

    builder = _Builder(system_names)
    ids = signals[SIGNAL_ID].astype(str).str.strip()
    for member in members:
        row = signals.loc[ids == member]
        if not row.empty:
            _add_hardwired_leg(builder, row.iloc[0], member)
    _add_bus_legs(builder, bundle.bus_payload, members)

    if not builder.nodes:
        return Dataflow(pd.DataFrame(), pd.DataFrame(), members)

    entries = list(builder.edges.values())
    positions, feedback = _layer_positions(list(builder.nodes), entries)

    nodes = pd.DataFrame(list(builder.nodes.values()))
    nodes["x"] = nodes["node_id"].map(lambda n: positions.get(n, (0.0, 0.0))[0])
    nodes["y"] = nodes["node_id"].map(lambda n: positions.get(n, (0.0, 0.0))[1])

    edges = pd.DataFrame(
        [
            {
                "source": entry["source"],
                "target": entry["target"],
                "interface": entry["interface"],
                "bus": entry["bus"],
                "allocations": len(entry["allocations"]),
                "label": _edge_label(entry),
                "hover": _edge_hover(entry, sid),
                # Legs contributed only by a relative, never by the selected signal.
                "related": sid not in entry["signals"],
                "feedback": (entry["source"], entry["target"]) in feedback,
            }
            for entry in entries
        ]
    )
    return Dataflow(nodes, edges, members, feedback)
