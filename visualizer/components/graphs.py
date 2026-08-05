"""Plotly / NetworkX graph builders."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from visualizer.data.models import (
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


def _lru_to_function(systems: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """Map equipment acronym -> (function acronym, function name)."""
    if systems.empty or "Acronym" not in systems.columns:
        return {}
    fn_names: dict[str, str] = {}
    if "Type" in systems.columns:
        for _, row in systems.iterrows():
            if str(row.get("Type") or "").strip().lower() != "system":
                continue
            acr = str(row.get("Acronym") or "").strip()
            if acr:
                fn_names[acr] = str(row.get("System Name") or acr).strip() or acr

    mapping: dict[str, tuple[str, str]] = {}
    if "Functional system" not in systems.columns:
        return mapping
    for _, row in systems.iterrows():
        acr = str(row.get("Acronym") or "").strip()
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


def _vis_edges_from_digraph(graph: nx.DiGraph) -> list[dict]:
    """Collapse opposite directed pairs; color from the owning bus topology."""
    emitted: set[tuple[str, str]] = set()
    vis_edges: list[dict] = []
    for src, tgt in graph.edges():
        pair = tuple(sorted((src, tgt)))
        if pair in emitted:
            continue
        emitted.add(pair)
        link_kind = _edge_link_kind(graph, src, tgt)
        if graph.has_edge(tgt, src):
            # Prefer shared coloring when both directions exist on a digital bus.
            if link_kind == TOPOLOGY_UNIDIRECTIONAL:
                other = _edge_link_kind(graph, tgt, src)
                if other == TOPOLOGY_SHARED:
                    link_kind = TOPOLOGY_SHARED
            color = topology_color(link_kind)
            label = formal_topology_label(link_kind) or link_kind
            vis_edges.append(
                {
                    "from": src,
                    "to": tgt,
                    "arrows": {"to": {"enabled": True}, "from": {"enabled": True}},
                    "color": {"color": color},
                    "width": 2 if link_kind == TOPOLOGY_SHARED else 1.5,
                    "smooth": {"type": "continuous"},
                    "title": label,
                }
            )
        else:
            color = topology_color(link_kind)
            label = formal_topology_label(link_kind) or link_kind
            # Shared-medium buses stay dual-arrow even when this LRU is RX-only.
            if link_kind == TOPOLOGY_SHARED:
                arrows = {"to": {"enabled": True}, "from": {"enabled": True}}
                width = 2
            else:
                arrows = {"to": {"enabled": True}}
                width = 1.5 if link_kind in {
                    TOPOLOGY_ANALOG,
                    TOPOLOGY_DISCRETE,
                    TOPOLOGY_POWER,
                } else 1
            vis_edges.append(
                {
                    "from": src,
                    "to": tgt,
                    "arrows": arrows,
                    "color": {"color": color},
                    "width": width,
                    "smooth": {"type": "continuous"},
                    "title": label,
                }
            )
    return vis_edges


def _build_function_regions(
    graph: nx.DiGraph,
    systems: pd.DataFrame,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (vis nodes, vis edges, region descriptors) for grouped generic view."""
    mapping = _lru_to_function(systems)
    members: dict[str, list[str]] = defaultdict(list)
    fn_label: dict[str, str] = {}
    buses: list[str] = []

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
        vis_nodes.append(
            {
                "id": bus_id,
                "label": bus_id,
                "title": f"{bus_id} ({mode or 'bus'}) — drag to reposition",
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

    regions: list[dict] = []
    if group_by_function:
        vis_nodes, vis_edges, regions = _build_function_regions(
            graph, systems if systems is not None else pd.DataFrame()
        )
        height = max(height, 720)
    else:
        vis_nodes = []
        for node_id, data in graph.nodes(data=True):
            kind = data.get("kind", "lru")
            mode = data.get("bus_mode", "")
            if kind == "bus":
                color = _bus_color(mode)
                tip = (
                    f"{node_id} ({mode or 'bus'}) — drag to reposition "
                    "(others stay pinned)"
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
                }
            )
        vis_edges = _vis_edges_from_digraph(graph)

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
            iterations: grouped ? 200 : 140,
            fit: true
          }},
          barnesHut: {{
            gravitationalConstant: grouped ? -12000 : -5000,
            springLength: grouped ? 200 : 110,
            springConstant: grouped ? 0.02 : 0.05,
            damping: 0.45,
            avoidOverlap: grouped ? 1 : 0.3
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
              gravitationalConstant: -3500,
              springLength: 110,
              springConstant: 0.04,
              damping: 0.55,
              avoidOverlap: 0.2
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


def signal_trace_figure(hops: pd.DataFrame) -> go.Figure:
    """Simple left-to-right hop diagram from ordered bus payload rows."""
    if hops.empty:
        fig = go.Figure()
        fig.update_layout(title="No hops", height=280)
        return fig

    labels = []
    hover = []
    for _, row in hops.iterrows():
        data_id = str(row.get("Allocation Id") or row.get("Data Id") or "").strip()
        data_name = str(row.get("data_name") or "").strip()
        writer = row.get("writer_lru", "")
        receivers = row.get("receiver_lrus", "")
        tab = row.get("definition_tab", "")
        role = row.get("hop_role", "")
        title = f"{data_id} — {data_name}" if data_name else data_id
        labels.append(f"{title}\n{writer} → {receivers}\n[{tab}] ({role})")
        hover.append(title)

    n = len(labels)
    xs = list(range(n))
    ys = [0] * n

    fig = go.Figure()
    if n > 1:
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line={"color": "#888", "width": 2},
                hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="markers+text",
            text=labels,
            textposition="top center",
            marker={"size": 22, "color": "#2ca02c"},
            hovertext=hover,
            hoverinfo="text",
        )
    )
    fig.update_layout(
        title="Signal hops (Id-linked bus rows)",
        height=400,
        showlegend=False,
        xaxis={"visible": False},
        yaxis={"visible": False},
        margin={"l": 40, "r": 40, "t": 60, "b": 40},
    )
    return fig
