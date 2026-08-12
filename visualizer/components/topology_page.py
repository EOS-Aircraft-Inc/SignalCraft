"""Bus Topology page: the interactive vis-network diagram.

The diagram is a small web page built here and handed to Streamlit. Its
JavaScript lives beside this file in bus_topology.js — edit that file to
change how the diagram behaves. Python only decides *what* to draw and passes
it over as one JSON object.

The vis-network library itself is read from the installed pyvis package, so the
page never fetches anything from the internet.
"""

from __future__ import annotations

import html
import importlib.util
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import networkx as nx
import pandas as pd
import streamlit as st

from visualizer.data.models import (
    ALLOCATION_ID,
    BUS_DEFINITION,
    SIGNAL_ID,
    SYSTEM_TEXTUAL_NAME,
    SYSTEM_UNIQUE_ID,
    TOPOLOGY_ANALOG,
    TOPOLOGY_COLORS,
    TOPOLOGY_DISCRETE,
    TOPOLOGY_POWER,
    TOPOLOGY_SHARED,
    TOPOLOGY_UNIDIRECTIONAL,
    formal_topology_label,
    normalize_bus_topology,
    topology_color,
)

_BUS_HOVER_ALLOC_LIMIT = 10

# vis-network ships inside pyvis; newest folder first.
_VIS_NETWORK_FOLDERS = ("vis-9.1.2", "vis-9.0.4")
_vis_network_js: str | None = None

# Bus / LRU colours for topology views.
COLOR_LRU = "#ff7f0e"
COLOR_BUS_MONO = TOPOLOGY_COLORS[TOPOLOGY_UNIDIRECTIONAL]
COLOR_BUS_SHARED = TOPOLOGY_COLORS[TOPOLOGY_SHARED]
COLOR_BUS_ANALOG = TOPOLOGY_COLORS[TOPOLOGY_ANALOG]
COLOR_BUS_DISCRETE = TOPOLOGY_COLORS[TOPOLOGY_DISCRETE]
COLOR_BUS_POWER = TOPOLOGY_COLORS[TOPOLOGY_POWER]
COLOR_BUS_DEFAULT = "#1f77b4"
COLOR_FUNCTION_FILL = "rgba(70, 130, 180, 0.10)"
COLOR_FUNCTION_BORDER = "#4682b4"

_INSTANCE_SUFFIX = re.compile(r"(-\d+)+$")


def _read_asset(name: str) -> str:
    """Read a file that ships next to this module (the diagram's JavaScript)."""
    path = Path(__file__).resolve().parent / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing diagram asset: {path}")
    return path.read_text(encoding="utf-8")


def _vis_network_source() -> str:
    """Return the vis-network library text shipped inside pyvis.

    Read from disk once, then kept in memory for the rest of the session.
    Raises ``FileNotFoundError`` with a fix-it message if pyvis is missing.
    """
    global _vis_network_js
    if _vis_network_js is not None:
        return _vis_network_js

    # Locate the package without importing it: "import pyvis" would load all of
    # IPython (~1s and 900 modules) and we only need the folder it sits in.
    spec = importlib.util.find_spec("pyvis")
    if spec is None or not spec.origin:
        raise FileNotFoundError(
            "The topology diagram needs the pyvis package. Run 'uv sync' "
            "from the SignalCraft repo root."
        )

    lib_dir = Path(spec.origin).resolve().parent / "lib"
    for folder in _VIS_NETWORK_FOLDERS:
        candidate = lib_dir / folder / "vis-network.min.js"
        if candidate.is_file():
            _vis_network_js = candidate.read_text(encoding="utf-8")
            return _vis_network_js

    raise FileNotFoundError(
        f"vis-network.min.js not found under {lib_dir}. Reinstall pyvis with "
        "'uv sync', or add the installed version to _VIS_NETWORK_FOLDERS."
    )


def _bus_color(bus_mode: object) -> str:
    return topology_color(bus_mode, default=COLOR_BUS_DEFAULT)


def _esc(value: object) -> str:
    return html.escape(str(value or "").strip())


def _bus_family_for_node(node_id: str, data: dict, buses: pd.DataFrame) -> str:
    family = str(data.get("family") or "").strip()
    if family:
        return family
    if buses.empty or "Bus Id" not in buses.columns:
        return node_id
    match = buses[buses["Bus Id"].astype(str) == node_id]
    if match.empty:
        return node_id
    row = match.iloc[0]
    return str(row.get(BUS_DEFINITION) or node_id).strip() or node_id


def _bus_meta_lines(node_id: str, family: str, mode: str, buses: pd.DataFrame) -> list[str]:
    lines = [f"<b>{_esc(node_id)}</b>"]
    if family and family != node_id:
        lines.append(f"Definition: {_esc(family)}")
    mode_label = formal_topology_label(mode) or mode or "bus"
    lines.append(f"Topology: {_esc(mode_label)}")
    if buses.empty:
        return lines

    if "Bus Id" in buses.columns:
        exact = buses[buses["Bus Id"].astype(str) == node_id]
    else:
        exact = buses.iloc[0:0]

    family_rows = buses.iloc[0:0]
    if BUS_DEFINITION in buses.columns:
        family_rows = buses[buses[BUS_DEFINITION].astype(str) == family]

    # Generic bus node (id == definition): summarize the family.
    if exact.empty and not family_rows.empty:
        lines.append(f"Instances: {len(family_rows)}")
        name = str(family_rows.iloc[0].get("name") or "").strip()
        if name:
            lines.append(_esc(name))
        protos = sorted(
            {str(v).strip() for v in family_rows.get("protocol", []) if str(v).strip()}
        )
        speeds = sorted(
            {str(v).strip() for v in family_rows.get("speed", []) if str(v).strip()}
        )
        proto_speed = " · ".join(
            p for p in (", ".join(_esc(x) for x in protos), ", ".join(_esc(x) for x in speeds))
            if p
        )
        if proto_speed:
            lines.append(proto_speed)
        return lines

    if exact.empty:
        return lines
    row = exact.iloc[0]
    name = str(row.get("name") or "").strip()
    if name:
        lines.append(_esc(name))
    proto = str(row.get("protocol") or "").strip()
    speed = str(row.get("speed") or "").strip()
    if proto or speed:
        lines.append(" · ".join(p for p in (_esc(proto), _esc(speed)) if p))
    sender = str(row.get("Sender") or "").strip()
    receiver = str(row.get("Receiver") or "").strip()
    if sender:
        lines.append(f"Sender: {_esc(sender)}")
    if receiver:
        lines.append(f"Receiver: {_esc(receiver)}")
    return lines


def _payload_hover_lines(
    family: str,
    bus_payload: pd.DataFrame,
    signals: pd.DataFrame | None,
    *,
    limit: int = _BUS_HOVER_ALLOC_LIMIT,
) -> list[str]:
    if not family or bus_payload is None or bus_payload.empty:
        return ["Allocations: (none)"]
    work = bus_payload
    if "definition_tab" in work.columns:
        work = work[work["definition_tab"].astype(str) == family]
    if work.empty:
        return ["Allocations: (none)"]

    name_by_sig: dict[str, str] = {}
    if signals is not None and not signals.empty and SIGNAL_ID in signals.columns:
        name_col = "Signal Name" if "Signal Name" in signals.columns else ""
        for _, srow in signals.iterrows():
            sid = str(srow.get(SIGNAL_ID) or "").strip()
            if sid and name_col:
                name_by_sig[sid] = str(srow.get(name_col) or "").strip()

    total = len(work)
    lines = [
        f"<b>Allocations</b> ({total})"
        if total <= limit
        else f"<b>Allocations</b> (first {limit} of {total})"
    ]
    for _, row in work.head(limit).iterrows():
        aid = str(row.get(ALLOCATION_ID) or row.get("Allocation Id") or "").strip()
        sid = str(row.get("Signal Id") or "").strip()
        data_name = str(row.get("Data name") or "").strip()
        label = data_name or name_by_sig.get(sid, "") or sid or "(unnamed)"
        writer = str(row.get("Sender") or "").strip()
        receivers = str(row.get("Receiver") or "").strip()
        path = ""
        if writer or receivers:
            path = f" — {_esc(writer)} -> {_esc(receivers)}"
        prefix = f"{_esc(aid)}: " if aid else ""
        lines.append(f"• {prefix}{_esc(label)}{path}")
    if total > limit:
        lines.append(f"… and {total - limit} more")
    return lines


def _bus_hover_title(
    node_id: str,
    data: dict,
    *,
    buses: pd.DataFrame,
    bus_payload: pd.DataFrame,
    signals: pd.DataFrame | None = None,
    limit: int = _BUS_HOVER_ALLOC_LIMIT,
) -> str:
    mode = str(data.get("bus_mode") or "").strip()
    family = _bus_family_for_node(node_id, data, buses)
    lines = _bus_meta_lines(node_id, family, mode, buses)
    lines.append("")
    lines.extend(
        _payload_hover_lines(family, bus_payload, signals, limit=limit)
    )
    return "<br>".join(lines)


def _bus_hover_map(
    graph: nx.DiGraph,
    *,
    buses: pd.DataFrame,
    bus_payload: pd.DataFrame,
    signals: pd.DataFrame | None = None,
) -> dict[str, str]:
    tips: dict[str, str] = {}
    buses = buses if buses is not None else pd.DataFrame()
    bus_payload = bus_payload if bus_payload is not None else pd.DataFrame()
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "bus":
            continue
        tips[node_id] = _bus_hover_title(
            node_id,
            data,
            buses=buses,
            bus_payload=bus_payload,
            signals=signals,
        )
    return tips


def _lru_to_function(systems: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """Map equipment UniqueId -> (domain UniqueId, domain name)."""
    if systems.empty or SYSTEM_UNIQUE_ID not in systems.columns:
        return {}
    fn_names: dict[str, str] = {}
    if "Type" in systems.columns:
        for _, row in systems.iterrows():
            if str(row.get("Type") or "").strip().lower() != "domain":
                continue
            acr = str(row.get(SYSTEM_UNIQUE_ID) or "").strip()
            if acr:
                fn_names[acr] = (
                    str(row.get(SYSTEM_TEXTUAL_NAME) or acr).strip() or acr
                )

    mapping: dict[str, tuple[str, str]] = {}
    if "Domain" not in systems.columns:
        return mapping
    for _, row in systems.iterrows():
        acr = str(row.get(SYSTEM_UNIQUE_ID) or "").strip()
        fsys = str(row.get("Domain") or "").strip()
        if acr and fsys:
            mapping[acr] = (fsys, fn_names.get(fsys, fsys))
    return mapping


def _resolve_function(
    node_id: str, mapping: dict[str, tuple[str, str]]
) -> tuple[str, str]:
    if node_id in mapping:
        return mapping[node_id]
    base = _INSTANCE_SUFFIX.sub("", node_id)
    if base in mapping:
        return mapping[base]
    return ("OTHER", "Other / unassigned")


def _filtered_digraph(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    *,
    bus_prefix: str = "",
) -> nx.DiGraph:
    edge_work = edges.copy()
    if bus_prefix:
        edge_work = edge_work[
            edge_work["bus_id"].astype(str).str.startswith(bus_prefix)
            | edge_work["source"].astype(str).str.startswith(bus_prefix)
            | edge_work["target"].astype(str).str.startswith(bus_prefix)
        ]

    typed = edge_work[edge_work["edge_type"].isin(["writes", "reads", "iface"])]
    if typed.empty:
        typed = edge_work

    graph = nx.DiGraph()
    kind_map = (
        nodes.set_index("node_id")["kind"].to_dict() if not nodes.empty else {}
    )
    mode_map = (
        nodes.set_index("node_id")["bus_mode"].to_dict()
        if not nodes.empty and "bus_mode" in nodes.columns
        else {}
    )
    for _, row in typed.iterrows():
        src = str(row["source"])
        tgt = str(row["target"])
        link_kind = str(row.get("link_kind") or "").strip()
        bus_id = str(row.get("bus_id") or "").strip()
        if not link_kind and bus_id:
            link_kind = str(mode_map.get(bus_id, "") or "")
        if not link_kind:
            link_kind = str(
                mode_map.get(src, "") or mode_map.get(tgt, "") or ""
            )
        graph.add_node(
            src,
            kind=kind_map.get(src, "lru"),
            bus_mode=str(mode_map.get(src, "") or ""),
        )
        graph.add_node(
            tgt,
            kind=kind_map.get(tgt, "lru"),
            bus_mode=str(mode_map.get(tgt, "") or ""),
        )
        graph.add_edge(
            src,
            tgt,
            edge_type=row.get("edge_type", ""),
            bus_id=bus_id,
            link_kind=normalize_bus_topology(link_kind) or link_kind,
        )
    return graph


def _edge_link_kind(graph: nx.DiGraph, src: str, tgt: str) -> str:
    data = graph.get_edge_data(src, tgt) or {}
    kind = normalize_bus_topology(data.get("link_kind"))
    if kind:
        return kind
    bus_id = str(data.get("bus_id") or "").strip()
    if bus_id and bus_id in graph.nodes:
        kind = normalize_bus_topology(graph.nodes[bus_id].get("bus_mode"))
        if kind:
            return kind
    for end in (src, tgt):
        if graph.nodes.get(end, {}).get("kind") == "bus":
            kind = normalize_bus_topology(graph.nodes[end].get("bus_mode"))
            if kind:
                return kind
    return TOPOLOGY_UNIDIRECTIONAL


def _layout_density(graph: nx.DiGraph) -> dict[str, float | int | bool]:
    """Return density-adaptive layout knobs for the non-grouped topology view.

    Sparse graphs keep today's defaults; dense Full-network hub graphs scale
    repulsion, spring length, overlap avoidance, iterations, and canvas height.
    """
    n = graph.number_of_nodes()
    e = graph.number_of_edges()
    max_deg = 0
    if n:
        max_deg = max(dict(graph.degree()).values(), default=0)

    # Soft thresholds: typical Generic stays near t=0; Full instances climb toward 1.
    t_n = max(0.0, min(1.0, (n - 40) / 80.0))
    t_e = max(0.0, min(1.0, (e - 60) / 120.0))
    t_d = max(0.0, min(1.0, (max_deg - 8) / 20.0))
    t = max(t_n, t_e, t_d)
    # Curved fan-out only for large graphs (Full network). High degree alone on a
    # small Generic map must not flip dense — that would wave Attach-2-style views.
    dense = bool(n > 60 or e > 100)

    def lerp(a: float, b: float) -> float:
        return a + (b - a) * t

    return {
        "dense": dense,
        "t": t,
        "n": n,
        "e": e,
        "max_deg": max_deg,
        "gravitationalConstant": lerp(-5000, -14000),
        "springLength": lerp(110, 180),
        "springConstant": lerp(0.05, 0.03),
        "avoidOverlap": lerp(0.3, 0.8),
        "iterations": round(lerp(140, 220)),
        "height": round(lerp(640, 900)),
        "postGravity": lerp(-3500, -9000),
        "postSpringLength": lerp(110, 160),
        "postSpringConstant": lerp(0.04, 0.03),
        "postAvoidOverlap": lerp(0.2, 0.6),
        "damping": 0.45,
        "postDamping": 0.55,
    }


def _node_mass(degree: int) -> float:
    """Heavier hubs so shared buses stay central while leaves spread out."""
    return 1.0 + min(max(degree, 0), 20) * 0.15


def _edge_smooth(dense: bool, index: int) -> dict[str, object]:
    if not dense:
        return {"type": "continuous"}
    return {
        "type": "curvedCW" if index % 2 == 0 else "curvedCCW",
        "roundness": 0.15 + (index % 5) * 0.025,
    }


def _vis_edges_from_digraph(
    graph: nx.DiGraph, *, dense: bool = False
) -> list[dict]:
    """Collapse opposite directed pairs; color from the owning bus topology."""
    emitted: set[tuple[str, str]] = set()
    vis_edges: list[dict] = []
    edge_index = 0
    for src, tgt in graph.edges():
        pair = tuple(sorted((src, tgt)))
        if pair in emitted:
            continue
        emitted.add(pair)
        link_kind = _edge_link_kind(graph, src, tgt)
        smooth = _edge_smooth(dense, edge_index)
        edge_index += 1
        if graph.has_edge(tgt, src):
            # Prefer shared coloring when both directions exist on a digital bus.
            if link_kind == TOPOLOGY_UNIDIRECTIONAL:
                other = _edge_link_kind(graph, tgt, src)
                if other == TOPOLOGY_SHARED:
                    link_kind = TOPOLOGY_SHARED
            color = topology_color(link_kind)
            label = formal_topology_label(link_kind) or link_kind
            # Power is undirected on the diagram (nominal flow is stored, not drawn).
            if link_kind == TOPOLOGY_POWER:
                arrows: dict = {
                    "to": {"enabled": False},
                    "from": {"enabled": False},
                }
                width = 1.5
            else:
                arrows = {"to": {"enabled": True}, "from": {"enabled": True}}
                width = 2 if link_kind == TOPOLOGY_SHARED else 1.5
            vis_edges.append(
                {
                    "from": src,
                    "to": tgt,
                    "arrows": arrows,
                    "color": {"color": color},
                    "width": width,
                    "smooth": smooth,
                    "title": label,
                }
            )
        else:
            color = topology_color(link_kind)
            label = formal_topology_label(link_kind) or link_kind
            if link_kind == TOPOLOGY_POWER:
                # Power supply: no arrowheads (bidirectional by nature).
                arrows = {"to": {"enabled": False}, "from": {"enabled": False}}
                width = 1.5
            elif link_kind == TOPOLOGY_SHARED:
                # Shared-medium buses stay dual-arrow even when this LRU is RX-only.
                arrows = {"to": {"enabled": True}, "from": {"enabled": True}}
                width = 2
            else:
                arrows = {"to": {"enabled": True}}
                width = 1.5 if link_kind in {
                    TOPOLOGY_ANALOG,
                    TOPOLOGY_DISCRETE,
                } else 1
            vis_edges.append(
                {
                    "from": src,
                    "to": tgt,
                    "arrows": arrows,
                    "color": {"color": color},
                    "width": width,
                    "smooth": smooth,
                    "title": label,
                }
            )
    return vis_edges


def _build_function_regions(
    graph: nx.DiGraph,
    systems: pd.DataFrame,
    *,
    bus_hovers: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (vis nodes, vis edges, region descriptors) for grouped generic view."""
    mapping = _lru_to_function(systems)
    members: dict[str, list[str]] = defaultdict(list)
    fn_label: dict[str, str] = {}
    buses: list[str] = []
    bus_hovers = bus_hovers or {}

    for node_id, data in graph.nodes(data=True):
        kind = data.get("kind", "lru")
        if kind == "bus":
            buses.append(node_id)
        else:
            fn_id, fn_name = _resolve_function(node_id, mapping)
            members[fn_id].append(node_id)
            fn_label[fn_id] = fn_name

    fn_ids = sorted(members.keys(), key=lambda k: (k == "OTHER", fn_label.get(k, k)))
    n_fn = max(len(fn_ids), 1)
    cols = max(1, math.ceil(math.sqrt(n_fn)))
    rows = max(1, math.ceil(n_fn / cols))

    max_members = max((len(v) for v in members.values()), default=1)
    inner_cols = max(1, math.ceil(math.sqrt(max_members)))
    inner_rows = max(1, math.ceil(max_members / inner_cols))
    pad = 40.0
    box_w = float(max(300, inner_cols * 90 + 2 * pad + 20))
    box_h = float(max(220, inner_rows * 58 + 2 * pad + 50))
    gap_x, gap_y = 80.0, 80.0

    regions: list[dict] = []
    vis_nodes: list[dict] = []

    for index, fn_id in enumerate(fn_ids):
        col = index % cols
        row = index // cols
        cx = col * (box_w + gap_x) + box_w / 2
        cy = row * (box_h + gap_y) + box_h / 2
        label = fn_label.get(fn_id, fn_id)
        regions.append(
            {
                "id": fn_id,
                "label": f"{label} ({fn_id})" if fn_id != label else label,
                "x": cx,
                "y": cy,
                "w": box_w,
                "h": box_h,
                "pad": pad,
                "members": members[fn_id],
            }
        )
        # Large box = the function square itself (physics places it, then we lock).
        vis_nodes.append(
            {
                "id": f"fn:{fn_id}",
                "label": fn_id,
                "title": f"{label} — drag to move this domain group",
                "color": {
                    "background": "rgba(220, 230, 242, 0.85)",
                    "border": COLOR_FUNCTION_BORDER,
                    "highlight": {
                        "background": "rgba(197, 212, 234, 0.95)",
                        "border": COLOR_FUNCTION_BORDER,
                    },
                },
                "shape": "box",
                "kind": "function",
                "function_id": fn_id,
                "x": cx,
                "y": cy,
                "widthConstraint": {"minimum": int(box_w), "maximum": int(box_w)},
                "heightConstraint": {"minimum": int(box_h), "maximum": int(box_h)},
                "borderWidth": 2,
                "borderWidthSelected": 3,
                "font": {
                    "size": 16,
                    "face": "arial",
                    "bold": True,
                    "vadjust": -int(box_h / 2) + 22,
                },
                "physics": True,
            }
        )

        lru_list = members[fn_id]
        local_cols = max(1, math.ceil(math.sqrt(max(len(lru_list), 1))))
        for j, lru in enumerate(lru_list):
            lc = j % local_cols
            lr = j // local_cols
            lx = cx - box_w / 2 + pad + 50 + lc * 85
            ly = cy - box_h / 2 + pad + 55 + lr * 55
            mode = graph.nodes[lru].get("bus_mode", "")
            vis_nodes.append(
                {
                    "id": lru,
                    "label": lru,
                    "title": f"{lru} (lru) in {fn_id}",
                    "color": COLOR_LRU,
                    "shape": "dot",
                    "kind": "lru",
                    "function_id": fn_id,
                    "bus_mode": mode,
                    "x": lx,
                    "y": ly,
                    "physics": False,
                }
            )

    bus_y = rows * (box_h + gap_y) + 60
    bus_gap = 170.0
    total_bus_width = max(len(buses) - 1, 0) * bus_gap
    bus_x0 = (cols * (box_w + gap_x) - gap_x) / 2 - total_bus_width / 2
    for i, bus_id in enumerate(sorted(buses)):
        mode = graph.nodes[bus_id].get("bus_mode", "")
        tip = bus_hovers.get(
            bus_id,
            f"{bus_id} ({mode or 'bus'}) — drag to reposition",
        )
        vis_nodes.append(
            {
                "id": bus_id,
                "label": bus_id,
                "title": tip,
                "color": _bus_color(mode),
                "shape": "box",
                "kind": "bus",
                "bus_mode": mode,
                "x": bus_x0 + i * bus_gap,
                "y": bus_y,
                "borderWidth": 2,
                "physics": True,
            }
        )

    vis_edges = _vis_edges_from_digraph(graph)
    return vis_nodes, vis_edges, regions


def render_draggable_bus_topology(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    *,
    title: str = "Bus topology",
    height: int = 640,
    group_by_function: bool = False,
    systems: pd.DataFrame | None = None,
    buses: pd.DataFrame | None = None,
    bus_payload: pd.DataFrame | None = None,
    signals: pd.DataFrame | None = None,
) -> None:
    """Interactive topology with pinned bus nodes and free LRU physics."""
    if edges.empty or nodes.empty:
        st.iframe(
            "<p style='font-family:sans-serif'>No topology data</p>",
            height=80,
        )
        return

    graph = _filtered_digraph(nodes, edges, bus_prefix="")
    if graph.number_of_nodes() == 0:
        st.iframe(
            "<p style='font-family:sans-serif'>No nodes</p>",
            height=80,
        )
        return

    hover_map = _bus_hover_map(
        graph,
        buses=buses if buses is not None else pd.DataFrame(),
        bus_payload=bus_payload if bus_payload is not None else pd.DataFrame(),
        signals=signals,
    )

    regions: list[dict] = []
    layout = _layout_density(graph)
    if group_by_function:
        vis_nodes, vis_edges, regions = _build_function_regions(
            graph,
            systems if systems is not None else pd.DataFrame(),
            bus_hovers=hover_map,
        )
        height = max(height, 720)
        phys_g = -12000.0
        phys_spring = 200.0
        phys_k = 0.02
        phys_overlap = 1.0
        phys_iters = 200
        post_g = -3500.0
        post_spring = 110.0
        post_k = 0.04
        post_overlap = 0.2
    else:
        height = max(height, int(layout["height"]))
        phys_g = float(layout["gravitationalConstant"])
        phys_spring = float(layout["springLength"])
        phys_k = float(layout["springConstant"])
        phys_overlap = float(layout["avoidOverlap"])
        phys_iters = int(layout["iterations"])
        post_g = float(layout["postGravity"])
        post_spring = float(layout["postSpringLength"])
        post_k = float(layout["postSpringConstant"])
        post_overlap = float(layout["postAvoidOverlap"])
        degrees = dict(graph.degree())
        dense = bool(layout["dense"])
        vis_nodes = []
        for node_id, data in graph.nodes(data=True):
            kind = data.get("kind", "lru")
            mode = data.get("bus_mode", "")
            if kind == "bus":
                color = _bus_color(mode)
                tip = hover_map.get(
                    node_id,
                    f"{node_id} ({mode or 'bus'}) — drag to reposition "
                    "(others stay pinned)",
                )
                shape = "box"
            else:
                color = COLOR_LRU
                tip = f"{node_id} (lru)"
                shape = "dot"
            vis_nodes.append(
                {
                    "id": node_id,
                    "label": node_id,
                    "title": tip,
                    "color": color,
                    "shape": shape,
                    "kind": kind,
                    "bus_mode": mode,
                    "mass": _node_mass(int(degrees.get(node_id, 0))),
                }
            )
        vis_edges = _vis_edges_from_digraph(graph, dense=dense)

    config_json = json.dumps(
        {
            "title": title,
            "grouped": bool(group_by_function),
            "regions": regions,
            "nodes": vis_nodes,
            "edges": vis_edges,
            "functionBorder": COLOR_FUNCTION_BORDER,
            # Physics tuning for the force layout, chosen from graph density.
            "layout": {
                "physG": phys_g,
                "physSpring": phys_spring,
                "physK": phys_k,
                "physOverlap": phys_overlap,
                "physIters": phys_iters,
                "postG": post_g,
                "postSpring": post_spring,
                "postK": post_k,
                "postOverlap": post_overlap,
            },
        }
    )
    app_js = _read_asset("bus_topology.js")
    try:
        vis_network_js = _vis_network_source()
    except FileNotFoundError as exc:
        st.error(f"Cannot draw the topology diagram: {exc}")
        return
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script>{vis_network_js}</script>
  <style>
    html, body {{ margin: 0; padding: 0; background: #fafafa; }}
    #wrap {{ position: relative; }}
    #title {{
      font-family: sans-serif; font-size: 14px; font-weight: 600;
      padding: 8px 10px 0 48px; color: #222;
    }}
    #toolbar {{
      position: absolute; top: 8px; left: 8px; z-index: 20;
      display: flex; flex-direction: column; gap: 4px;
    }}
    #toolbar button {{
      width: 32px; height: 32px; padding: 0; cursor: pointer;
      border: 1px solid #bbb; border-radius: 4px; background: #fff;
      font-size: 16px; line-height: 1; color: #333;
      box-shadow: 0 1px 2px rgba(0,0,0,0.08);
    }}
    #toolbar button:hover {{ background: #f0f0f0; }}
    #topo {{ width: 100%; height: {height}px; border: 1px solid #ddd; background: #fafafa; }}
    .legend {{
      font-family: sans-serif; font-size: 12px; padding: 6px 10px 6px 48px; color: #333;
    }}
    .swatch {{
      display: inline-block; width: 12px; height: 12px; margin-right: 4px;
      border: 1px solid #333; vertical-align: middle;
    }}
  </style>
</head>
<body>
  <div id="wrap">
    <div id="toolbar">
      <button type="button" id="btn-home" title="Fit view (home)">⌂</button>
      <button type="button" id="btn-full" title="Fullscreen">⛶</button>
      <button type="button" id="btn-save" title="Save as PNG">💾</button>
    </div>
    <div id="title"></div>
    <div class="legend">
      <span class="swatch" style="background:{COLOR_LRU}"></span> LRU
      &nbsp;&nbsp;
      <span class="swatch" style="background:{COLOR_BUS_POWER}"></span> Power
      &nbsp;&nbsp;
      <span class="swatch" style="background:{COLOR_BUS_ANALOG}"></span> Analog
      &nbsp;&nbsp;
      <span class="swatch" style="background:{COLOR_BUS_DISCRETE}"></span> Discrete
      &nbsp;&nbsp;
      <span class="swatch" style="background:{COLOR_BUS_MONO}"></span> Digital mono
      &nbsp;&nbsp;
      <span class="swatch" style="background:{COLOR_BUS_SHARED}"></span> Digital shared
      &nbsp;&nbsp;
      <span class="swatch" style="background:{COLOR_FUNCTION_BORDER}"></span> Domain group
      &nbsp;&nbsp;· link color follows the bus Topology (not the LRU role)
    </div>
    <div id="topo"></div>
  </div>
  <script>window.SIGNALCRAFT_TOPOLOGY = {config_json};</script>
  <script>{app_js}</script>
</body>
</html>
"""
    st.iframe(html, height=height + 90, width="stretch")
