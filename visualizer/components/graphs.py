"""Plotly figures for the Signal Explorer and Bus Explorer pages.

The Bus Topology diagram is a different technology and lives in
topology_page.py beside this file.
"""

from __future__ import annotations

import math
import re

import plotly.graph_objects as go

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
from visualizer.data.models import topology_color

_INSTANCE_SUFFIX = re.compile(r"(-\d+)+$")


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
