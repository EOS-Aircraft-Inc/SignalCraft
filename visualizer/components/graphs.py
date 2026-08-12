"""Plotly / NetworkX graph builders."""

from __future__ import annotations

import html
import json
import math
import re
from collections import defaultdict

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from visualizer.data.bus_instances import (
    BUS_ROLE_COLORS,
    BUS_ROLE_LABELS,
    DIRECTION_BOTH,
    DIRECTION_FROM_BUS,
    DIRECTION_TO_BUS,
    ROLE_BUS,
    BusInstanceGraph,
)
from visualizer.data.dataflow import (
    INTERFACE_TOPOLOGY,
    NODE_EFFECTOR,
    NODE_SENSOR,
    NODE_SYSTEM,
    Dataflow,
)
from visualizer.data.models import (
    ALLOCATION_ID,
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
    return str(
        row.get("definition_tab") or row.get("Bus Definition") or node_id
    ).strip() or node_id


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
    if "definition_tab" in buses.columns:
        family_rows = buses[buses["definition_tab"].astype(str) == family]
    elif "Bus Definition" in buses.columns:
        family_rows = buses[buses["Bus Definition"].astype(str) == family]

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
    writer = str(row.get("Writer") or "").strip()
    receiver = str(row.get("Receiver") or "").strip()
    if writer:
        lines.append(f"Writer: {_esc(writer)}")
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
    lines = [f"<b>Allocations</b> ({total})" if total <= limit else f"<b>Allocations</b> (first {limit} of {total})"]
    for _, row in work.head(limit).iterrows():
        aid = str(row.get(ALLOCATION_ID) or row.get("Allocation Id") or "").strip()
        sid = str(row.get("signal_id") or "").strip()
        data_name = str(row.get("data_name") or "").strip()
        label = data_name or name_by_sig.get(sid, "") or sid or "(unnamed)"
        writer = str(row.get("writer_lru") or "").strip()
        receivers = str(row.get("receiver_lrus") or "").strip()
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
    """Map equipment UniqueId -> (function UniqueId, function name)."""
    if systems.empty or SYSTEM_UNIQUE_ID not in systems.columns:
        return {}
    fn_names: dict[str, str] = {}
    if "Type" in systems.columns:
        for _, row in systems.iterrows():
            if str(row.get("Type") or "").strip().lower() != "system":
                continue
            acr = str(row.get(SYSTEM_UNIQUE_ID) or "").strip()
            if acr:
                fn_names[acr] = (
                    str(row.get(SYSTEM_TEXTUAL_NAME) or acr).strip() or acr
                )

    mapping: dict[str, tuple[str, str]] = {}
    if "Functional system" not in systems.columns:
        return mapping
    for _, row in systems.iterrows():
        acr = str(row.get(SYSTEM_UNIQUE_ID) or "").strip()
        fsys = str(row.get("Functional system") or "").strip()
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
        "iterations": int(round(lerp(140, 220))),
        "height": int(round(lerp(640, 900))),
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
                "title": f"{label} — drag to move this function group",
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
                "font": {"size": 16, "face": "arial", "bold": True, "vadjust": -int(box_h / 2) + 22},
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

    nodes_json = json.dumps(vis_nodes)
    edges_json = json.dumps(vis_edges)
    regions_json = json.dumps(regions)
    title_js = json.dumps(title)
    grouped_js = "true" if group_by_function else "false"
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
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
      <span class="swatch" style="background:{COLOR_FUNCTION_BORDER}"></span> Function group
      &nbsp;&nbsp;· link color follows the bus Topology (not the LRU role)
    </div>
    <div id="topo"></div>
  </div>
  <script>
    document.getElementById("title").textContent = {title_js};
    const grouped = {grouped_js};
    const regions = {regions_json};
    const regionById = {{}};
    regions.forEach(function (r) {{ regionById[r.id] = r; }});

    const nodes = new vis.DataSet({nodes_json});
    const edges = new vis.DataSet({edges_json});
    const container = document.getElementById("topo");
    let draggingId = null;
    let dragKind = null;
    let lastDragPos = null;
    let layoutDone = false;
    let savedView = null;

    function captureView() {{
      return {{
        scale: network.getScale(),
        position: network.getViewPosition()
      }};
    }}
    function restoreView(view) {{
      if (!view) return;
      network.moveTo({{
        scale: view.scale,
        position: view.position,
        animation: false
      }});
    }}
    function pinNode(id) {{
      const n = nodes.get(id);
      if (!n) return;
      nodes.update({{
        id: id,
        fixed: {{ x: true, y: true }},
        borderWidth: n.kind === "lru" ? 1 : 3
      }});
    }}
    function unpinNode(id) {{
      nodes.update({{ id: id, fixed: {{ x: false, y: false }} }});
    }}

    function syncRegionsFromFunctions() {{
      nodes.forEach(function (n) {{
        if (n.kind !== "function") return;
        const pos = network.getPositions([n.id])[n.id];
        if (!pos) return;
        const r = regionById[n.function_id];
        if (!r) return;
        r.x = pos.x;
        r.y = pos.y;
      }});
    }}

    function placeLrusInRegions() {{
      regions.forEach(function (r) {{
        const members = r.members || [];
        const cols = Math.max(1, Math.ceil(Math.sqrt(Math.max(members.length, 1))));
        const pad = r.pad || 40;
        members.forEach(function (mid, j) {{
          const lc = j % cols;
          const lr = Math.floor(j / cols);
          const x = r.x - r.w / 2 + pad + 50 + lc * 85;
          const y = r.y - r.h / 2 + pad + 55 + lr * 55;
          nodes.update({{
            id: mid,
            x: x,
            y: y,
            fixed: {{ x: true, y: true }}
          }});
        }});
      }});
    }}

    function clampLruToRegion(n) {{
      if (!n || n.kind !== "lru" || !n.function_id) return;
      const r = regionById[n.function_id];
      if (!r) return;
      const pos = network.getPositions([n.id])[n.id] || n;
      const pad = r.pad || 30;
      const minX = r.x - r.w / 2 + pad;
      const maxX = r.x + r.w / 2 - pad;
      const minY = r.y - r.h / 2 + pad + 24;
      const maxY = r.y + r.h / 2 - pad;
      const x = Math.min(maxX, Math.max(minX, pos.x));
      const y = Math.min(maxY, Math.max(minY, pos.y));
      nodes.update({{ id: n.id, x: x, y: y }});
    }}

    const network = new vis.Network(
      container,
      {{ nodes, edges }},
      {{
        physics: {{
          enabled: true,
          stabilization: {{
            enabled: true,
            iterations: grouped ? 200 : {phys_iters},
            fit: true
          }},
          barnesHut: {{
            gravitationalConstant: grouped ? -12000 : {phys_g},
            springLength: grouped ? 200 : {phys_spring},
            springConstant: grouped ? 0.02 : {phys_k},
            damping: 0.45,
            avoidOverlap: grouped ? 1 : {phys_overlap}
          }}
        }},
        interaction: {{
          dragNodes: true,
          dragView: true,
          zoomView: true,
          hover: true,
          tooltipDelay: 120,
          hideEdgesOnDrag: false,
          multiselect: false
        }},
        nodes: {{ font: {{ size: 12 }}, borderWidth: 1 }},
        edges: {{ smooth: {{ type: "continuous" }}, selectionWidth: 1 }}
      }}
    );

    document.getElementById("btn-home").onclick = function () {{
      network.fit({{ animation: {{ duration: 250, easingFunction: "easeInOutQuad" }}, padding: 30 }});
    }};
    document.getElementById("btn-full").onclick = function () {{
      const el = document.getElementById("wrap");
      if (!document.fullscreenElement) {{
        if (el.requestFullscreen) el.requestFullscreen();
        else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
      }} else if (document.exitFullscreen) {{
        document.exitFullscreen();
      }}
    }};
    document.getElementById("btn-save").onclick = function () {{
      const canvas = network.canvas && network.canvas.frame && network.canvas.frame.canvas;
      if (!canvas) return;
      const link = document.createElement("a");
      link.download = "bus_topology.png";
      link.href = canvas.toDataURL("image/png");
      link.click();
    }};

    network.on("afterDrawing", function (ctx) {{
      if (!grouped || !regions.length) return;
      regions.forEach(function (r) {{
        const left = r.x - r.w / 2;
        const top = r.y - r.h / 2;
        ctx.save();
        ctx.strokeStyle = "{COLOR_FUNCTION_BORDER}";
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.strokeRect(left, top, r.w, r.h);
        ctx.setLineDash([]);
        ctx.fillStyle = "#333";
        ctx.font = "12px arial";
        ctx.fillText(r.label, left + 10, top + 16);
        ctx.restore();
      }});
    }});

    if (grouped) {{
      network.on("stabilizationProgress", function () {{
        syncRegionsFromFunctions();
        placeLrusInRegions();
      }});
    }}

    network.once("stabilizationIterationsDone", function () {{
      if (grouped) {{
        syncRegionsFromFunctions();
        placeLrusInRegions();
        layoutDone = true;
        nodes.forEach(function (n) {{
          if (n.kind === "function" || n.kind === "bus" || n.kind === "lru") {{
            pinNode(n.id);
          }}
        }});
        network.setOptions({{ physics: {{ enabled: false }} }});
      }} else {{
        nodes.forEach(function (n) {{
          if (n.kind === "bus") pinNode(n.id);
        }});
        network.setOptions({{
          physics: {{
            enabled: true,
            stabilization: {{ enabled: true, fit: false }},
            barnesHut: {{
              gravitationalConstant: {post_g},
              springLength: {post_spring},
              springConstant: {post_k},
              damping: 0.55,
              avoidOverlap: {post_overlap}
            }}
          }}
        }});
      }}
      // Initial fit only — later drags must not re-fit.
      network.fit({{ animation: false, padding: 30 }});
    }});

    network.on("dragStart", function (params) {{
      if (!params.nodes || params.nodes.length !== 1) return;
      const id = params.nodes[0];
      const n = nodes.get(id);
      if (!n) return;
      draggingId = id;
      dragKind = n.kind;
      savedView = captureView();
      const pos = network.getPositions([id])[id];
      lastDragPos = pos ? {{ x: pos.x, y: pos.y }} : null;
      unpinNode(id);
    }});

    network.on("dragging", function () {{
      if (!grouped || dragKind !== "function" || !draggingId || !lastDragPos) return;
      const pos = network.getPositions([draggingId])[draggingId];
      if (!pos) return;
      const dx = pos.x - lastDragPos.x;
      const dy = pos.y - lastDragPos.y;
      lastDragPos = {{ x: pos.x, y: pos.y }};
      const fnId = nodes.get(draggingId).function_id;
      const r = regionById[fnId];
      if (!r) return;
      r.x += dx;
      r.y += dy;
      const updates = [];
      (r.members || []).forEach(function (mid) {{
        const p = network.getPositions([mid])[mid];
        if (!p) return;
        updates.push({{
          id: mid,
          x: p.x + dx,
          y: p.y + dy,
          fixed: {{ x: true, y: true }}
        }});
      }});
      if (updates.length) nodes.update(updates);
    }});

    network.on("dragEnd", function () {{
      if (!draggingId) return;
      const n = nodes.get(draggingId);
      const pos = network.getPositions([draggingId])[draggingId];
      if (pos) nodes.update({{ id: draggingId, x: pos.x, y: pos.y }});

      if (dragKind === "function" && n) {{
        const r = regionById[n.function_id];
        if (r && pos) {{
          r.x = pos.x;
          r.y = pos.y;
        }}
        pinNode(draggingId);
        placeLrusInRegions();
        restoreView(savedView);
      }} else if (dragKind === "lru" && grouped) {{
        clampLruToRegion(nodes.get(draggingId));
        pinNode(draggingId);
        restoreView(savedView);
      }} else if (dragKind === "bus") {{
        pinNode(draggingId);
        if (!grouped) {{
          const view = savedView || captureView();
          network.setOptions({{
            physics: {{
              enabled: true,
              stabilization: {{ enabled: true, fit: false, iterations: 40 }}
            }}
          }});
          network.once("stabilized", function () {{
            restoreView(view);
          }});
          network.stabilize(40);
        }} else {{
          restoreView(savedView);
        }}
      }} else {{
        pinNode(draggingId);
        restoreView(savedView);
      }}
      draggingId = null;
      dragKind = null;
      lastDragPos = null;
      savedView = null;
    }});
  </script>
</body>
</html>
"""
    st.iframe(html, height=height + 90, width="stretch")


_DATAFLOW_SYSTEM_COLOR = "#7f8c9a"
_DATAFLOW_SYMBOLS = {
    NODE_SYSTEM: "circle",
    NODE_SENSOR: "diamond",
    NODE_EFFECTOR: "square",
}
_FEEDBACK_BOW = 0.35
_HEAD_STANDOFF = 0.13  # data units, keeps the arrowhead clear of the node marker


def _dataflow_color(interface: str) -> str:
    return topology_color(
        INTERFACE_TOPOLOGY.get(interface, ""), default=_DATAFLOW_SYSTEM_COLOR
    )


def signal_dataflow_figure(flow: Dataflow) -> go.Figure:
    """Layered left-to-right dataflow: hardwired legs plus bus legs."""
    fig = go.Figure()
    if flow.empty:
        fig.update_layout(
            title="No dataflow declared for this signal",
            height=240,
            xaxis={"visible": False},
            yaxis={"visible": False},
        )
        return fig

    pos = {row.node_id: (row.x, row.y) for row in flow.nodes.itertuples()}
    annotations: list[dict] = []
    hover_x: list[float] = []
    hover_y: list[float] = []
    hover_text: list[str] = []
    # Arrowheads as oriented markers, not annotation arrows: annotation arrows
    # draw a solid tail that a dotted leg cannot inherit.
    head_x: list[float] = []
    head_y: list[float] = []
    head_size: list[int] = []
    head_color: list[str] = []

    for (interface, related), group in flow.edges.groupby(
        ["interface", "related"], sort=False
    ):
        color = _dataflow_color(str(interface))
        xs: list[float | None] = []
        ys: list[float | None] = []
        for edge in group.itertuples():
            if edge.source not in pos or edge.target not in pos:
                continue
            x0, y0 = pos[edge.source]
            x1, y1 = pos[edge.target]
            if edge.feedback:
                # Bow a cycle-closing leg away from its forward twin.
                mid_x, mid_y = (x0 + x1) / 2, (y0 + y1) / 2 + _FEEDBACK_BOW
                xs += [x0, mid_x, x1, None]
                ys += [y0, mid_y, y1, None]
                tail_x, tail_y = mid_x, mid_y
            else:
                mid_x, mid_y = (x0 + x1) / 2, (y0 + y1) / 2
                xs += [x0, x1, None]
                ys += [y0, y1, None]
                tail_x, tail_y = x0, y0
            # Pair of points per head: the tail sizes to 0 and only orients the
            # marker, which plotly angles along the on-screen direction.
            span = math.hypot(x1 - tail_x, y1 - tail_y) or 1.0
            head_x += [tail_x, x1 - _HEAD_STANDOFF * (x1 - tail_x) / span]
            head_y += [tail_y, y1 - _HEAD_STANDOFF * (y1 - tail_y) / span]
            head_size += [0, 13]
            head_color += [color, color]
            annotations.append(
                {
                    "x": mid_x,
                    "y": mid_y,
                    "xref": "x",
                    "yref": "y",
                    "text": edge.label,
                    "showarrow": False,
                    "font": {"size": 10, "color": color},
                    "bgcolor": "rgba(17,17,17,0.55)",
                    "borderpad": 2,
                    "yshift": 10,
                }
            )
            hover_x.append(mid_x)
            hover_y.append(mid_y)
            hover_text.append(edge.hover)

        name = f"{interface} (via related)" if related else str(interface)
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line={"color": color, "width": 2, "dash": "dot" if related else "solid"},
                name=name,
                legendgroup=name,
                hoverinfo="skip",
            )
        )

    fig.add_trace(
        go.Scatter(
            x=head_x,
            y=head_y,
            mode="markers",
            marker={
                "symbol": "arrow",
                "angleref": "previous",
                "size": head_size,
                "color": head_color,
                "line": {"width": 0},
            },
            hoverinfo="skip",
            showlegend=False,
        )
    )

    fig.add_trace(
        go.Scatter(
            x=hover_x,
            y=hover_y,
            mode="markers",
            marker={"size": 14, "color": "rgba(0,0,0,0)"},
            hovertext=hover_text,
            hoverinfo="text",
            showlegend=False,
        )
    )

    for kind, group in flow.nodes.groupby("kind", sort=False):
        is_system = kind == NODE_SYSTEM
        colors = [
            _DATAFLOW_SYSTEM_COLOR if is_system else _dataflow_color(str(interface))
            for interface in group["interface"]
        ]
        fig.add_trace(
            go.Scatter(
                x=group["x"],
                y=group["y"],
                mode="markers+text",
                text=group["label"],
                textposition="bottom center",
                textfont={"size": 11},
                marker={
                    "size": 26 if is_system else 20,
                    "color": colors,
                    "symbol": _DATAFLOW_SYMBOLS.get(str(kind), "circle"),
                    "line": {"color": "#e6e6e6", "width": 1},
                },
                hovertext=[
                    f"{row.label}<br>{row.title}" if row.title else str(row.label)
                    for row in group.itertuples()
                ],
                hoverinfo="text",
                name=str(kind),
                showlegend=not is_system,
            )
        )

    rows = float(flow.nodes["y"].max() - flow.nodes["y"].min()) + 1.0
    fig.update_layout(
        height=int(min(900, max(320, 110 * rows))),
        annotations=annotations,
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        xaxis={
            "visible": False,
            "range": [flow.nodes["x"].min() - 0.6, flow.nodes["x"].max() + 0.6],
        },
        yaxis={
            "visible": False,
            "range": [flow.nodes["y"].min() - 0.9, flow.nodes["y"].max() + 0.9],
        },
        margin={"l": 30, "r": 30, "t": 50, "b": 30},
    )
    return fig


def bus_instance_figure(graph: BusInstanceGraph) -> go.Figure:
    """One star per bus instance: LRU nodes colored by their role on that bus."""
    fig = go.Figure()
    if graph.empty:
        fig.update_layout(
            title="No instances declared for this bus definition",
            height=240,
            xaxis={"visible": False},
            yaxis={"visible": False},
        )
        return fig

    pos = {row.node_id: (row.x, row.y) for row in graph.nodes.itertuples()}
    head_x: list[float] = []
    head_y: list[float] = []
    head_size: list[int] = []
    head_color: list[str] = []

    for role, group in graph.edges.groupby("role", sort=False):
        color = BUS_ROLE_COLORS.get(str(role), _DATAFLOW_SYSTEM_COLOR)
        xs: list[float | None] = []
        ys: list[float | None] = []
        for edge in group.itertuples():
            if edge.lru not in pos or edge.bus not in pos:
                continue
            lru_x, lru_y = pos[edge.lru]
            bus_x, bus_y = pos[edge.bus]
            xs += [lru_x, bus_x, None]
            ys += [lru_y, bus_y, None]
            ends = []
            if edge.direction in (DIRECTION_TO_BUS, DIRECTION_BOTH):
                ends.append(((lru_x, lru_y), (bus_x, bus_y)))
            if edge.direction in (DIRECTION_FROM_BUS, DIRECTION_BOTH):
                ends.append(((bus_x, bus_y), (lru_x, lru_y)))
            for (tail_x, tail_y), (tip_x, tip_y) in ends:
                span = math.hypot(tip_x - tail_x, tip_y - tail_y) or 1.0
                head_x += [tail_x, tip_x - _HEAD_STANDOFF * (tip_x - tail_x) / span]
                head_y += [tail_y, tip_y - _HEAD_STANDOFF * (tip_y - tail_y) / span]
                head_size += [0, 12]
                head_color += [color, color]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line={"color": color, "width": 1.6},
                hoverinfo="skip",
                showlegend=False,
            )
        )

    fig.add_trace(
        go.Scatter(
            x=head_x,
            y=head_y,
            mode="markers",
            marker={
                "symbol": "arrow",
                "angleref": "previous",
                "size": head_size,
                "color": head_color,
                "line": {"width": 0},
            },
            hoverinfo="skip",
            showlegend=False,
        )
    )

    for role, group in graph.nodes.groupby("role", sort=False):
        is_bus = role == ROLE_BUS
        fig.add_trace(
            go.Scatter(
                x=group["x"],
                y=group["y"],
                mode="markers+text",
                text=group["label"],
                textposition=group["text_position"],
                textfont={"size": 10},
                marker={
                    "size": 22 if is_bus else 16,
                    "color": BUS_ROLE_COLORS.get(str(role), _DATAFLOW_SYSTEM_COLOR),
                    "symbol": "square" if is_bus else "circle",
                    "line": {"color": "#e6e6e6", "width": 1},
                },
                hovertext=group["hover"],
                hoverinfo="text",
                name=BUS_ROLE_LABELS.get(str(role), str(role)),
            )
        )

    rows = float(graph.nodes["y"].max() - graph.nodes["y"].min()) + 1.0
    fig.update_layout(
        height=int(min(1500, max(320, 44 * rows))),
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        xaxis={"visible": False, "range": [-1.15, 3.15]},
        yaxis={
            "visible": False,
            "range": [graph.nodes["y"].min() - 0.9, graph.nodes["y"].max() + 0.9],
        },
        margin={"l": 20, "r": 20, "t": 50, "b": 20},
    )
    return fig
