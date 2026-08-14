"""Bus Topology page — full network and generic definition views."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from visualizer.components.tables import show_dataframe
from visualizer.components.topology_page import render_draggable_bus_topology
from visualizer.data.loader import IcdBundle
from visualizer.data.models import (
    BUS_DEFINITION,
    BUS_NAME,
    PROTOCOL,
    TOPOLOGY,
    TOPOLOGY_ANALOG,
    TOPOLOGY_DISCRETE,
    TOPOLOGY_HIGH_POWER,
    TOPOLOGY_LOW_POWER,
    TOPOLOGY_SHARED,
    TOPOLOGY_UNIDIRECTIONAL,
)

_INTERFACE_KINDS = {
    TOPOLOGY_ANALOG,
    TOPOLOGY_DISCRETE,
    TOPOLOGY_LOW_POWER,
    TOPOLOGY_HIGH_POWER,
}
_DIGITAL_KINDS = {TOPOLOGY_UNIDIRECTIONAL, TOPOLOGY_SHARED}
_LINK_KINDS = _INTERFACE_KINDS | _DIGITAL_KINDS


def _bus_families(buses) -> list[str]:
    if buses.empty:
        return []
    column = BUS_DEFINITION if BUS_DEFINITION in buses.columns else ""
    if column:
        values = [str(v).strip() for v in buses[column].tolist() if str(v).strip()]
        return sorted(set(values))
    return sorted({str(v) for v in buses["Bus Id"].astype(str).unique() if str(v).strip()})


def _edges_for_family(edges, nodes, buses, family: str):
    """Keep edges whose bus belongs to the selected Bus Definition family."""
    if edges.empty:
        return edges
    bus_ids: set[str] = set()
    if not nodes.empty and "family" in nodes.columns:
        bus_ids = set(
            nodes.loc[
                (nodes["kind"] == "bus") & (nodes["family"].astype(str) == family),
                "node_id",
            ].astype(str)
        )
    if not bus_ids and not buses.empty and BUS_DEFINITION in buses.columns:
        bus_ids = set(
            buses.loc[buses[BUS_DEFINITION].astype(str) == family, "Bus Id"]
            .astype(str)
            .tolist()
        )
    if not bus_ids:
        # Generic view: the bus node id is the family name itself.
        bus_ids = {family}
    return edges[
        edges["bus_id"].astype(str).isin(bus_ids)
        | edges["source"].astype(str).isin(bus_ids)
        | edges["target"].astype(str).isin(bus_ids)
    ]


def _nodes_touched_by_edges(nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    if nodes.empty:
        return nodes
    if edges.empty:
        return nodes.iloc[0:0]
    touched = set(edges["source"].astype(str)) | set(edges["target"].astype(str))
    return nodes[nodes["node_id"].astype(str).isin(touched)].copy()


def _apply_node_filters(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    *,
    selected_buses: list[str],
    selected_lrus: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep selected bus/LRU nodes and only edges between kept nodes."""
    keep = set(selected_buses) | set(selected_lrus)
    if not keep:
        empty_nodes = nodes.iloc[0:0]
        empty_edges = edges.iloc[0:0]
        return empty_nodes, empty_edges
    plot_nodes = nodes[nodes["node_id"].astype(str).isin(keep)].copy()
    if edges.empty:
        return plot_nodes, edges
    plot_edges = edges[
        edges["source"].astype(str).isin(keep) & edges["target"].astype(str).isin(keep)
    ].copy()
    return plot_nodes, plot_edges


def _filter_link_kinds(
    edges: pd.DataFrame,
    *,
    show_mono: bool,
    show_shared: bool,
    show_analog: bool,
    show_discrete: bool,
    show_low_power: bool,
    show_high_power: bool,
) -> pd.DataFrame:
    """Keep only edges whose link_kind is enabled by the layer toggles."""
    if edges.empty or "link_kind" not in edges.columns:
        return edges
    allowed: set[str] = set()
    if show_mono:
        allowed.add(TOPOLOGY_UNIDIRECTIONAL)
    if show_shared:
        allowed.add(TOPOLOGY_SHARED)
    if show_analog:
        allowed.add(TOPOLOGY_ANALOG)
    if show_discrete:
        allowed.add(TOPOLOGY_DISCRETE)
    if show_low_power:
        allowed.add(TOPOLOGY_LOW_POWER)
    if show_high_power:
        allowed.add(TOPOLOGY_HIGH_POWER)
    kinds = edges["link_kind"].astype(str)
    # Unknown / empty kinds stay visible only when at least one digital layer is on.
    known = kinds.isin(_LINK_KINDS)
    keep = (known & kinds.isin(allowed)) | ((~known) & (show_mono or show_shared))
    return edges.loc[keep].copy()


def _lru_neighbors_one_hop(
    selected_lrus: list[str],
    edges: pd.DataFrame,
    nodes: pd.DataFrame,
    *,
    lru_universe: list[str] | set[str],
) -> list[str]:
    """Expand selection with LRUs one hop away on the filtered graph.

    A hop is either a direct hardwired LRU↔LRU edge or an
    LRU–bus–LRU path on a databus.
    """
    selected = {str(x).strip() for x in selected_lrus if str(x).strip()}
    universe = {str(x).strip() for x in lru_universe if str(x).strip()}
    if not selected:
        return []
    if edges.empty or not universe:
        return sorted(selected & universe)

    kind_map: dict[str, str] = {}
    if not nodes.empty and "node_id" in nodes.columns and "kind" in nodes.columns:
        kind_map = {
            str(nid): str(kind)
            for nid, kind in zip(
                nodes["node_id"].astype(str), nodes["kind"].astype(str), strict=False
            )
        }

    adj: dict[str, set[str]] = {}
    for _, row in edges.iterrows():
        a = str(row.get("source") or "").strip()
        b = str(row.get("target") or "").strip()
        if not a or not b:
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    found = set(selected)
    for lru in selected:
        for nb in adj.get(lru, ()):
            nb_kind = kind_map.get(nb, "lru")
            if nb_kind != "bus":
                if nb in universe:
                    found.add(nb)
                continue
            for peer in adj.get(nb, ()):
                if peer == lru:
                    continue
                if kind_map.get(peer, "lru") == "bus":
                    continue
                if peer in universe:
                    found.add(peer)
    return sorted(found & universe)


def render(bundle: IcdBundle) -> None:
    st.header("Bus Topology")

    view = st.radio(
        "View",
        ["Full network", "Generic view"],
        horizontal=True,
        key="topo_view_mode",
        help=(
            "Full network uses every physical bus and LRU instance from 10_Databuses "
            "Sender/Receiver. Generic view keeps one node per Bus Definition and "
            "bare system acronyms (no instance expansion)."
        ),
    )
    generic = view == "Generic view"
    group_by_function = False

    if generic:
        st.caption(
            "Generic map: one node per Bus Definition; LRUs are bare acronyms "
            "(PACK, BMU, EPECS, …). Analog / Discrete / Low Power / High Power are "
            "direct colored "
            "LRU↔LRU links (no hub box). Buses stay pinned; drag one bus — "
            "LRUs re-settle."
        )
        group_by_function = st.checkbox(
            "Group per domain",
            value=False,
            key="topo_group_by_function",
            help=(
                "Place LRU nodes inside non-overlapping boxes for each "
                "0_Systems row with Type = Domain (via the Domain column)."
            ),
        )
        nodes = bundle.generic_nodes
        edges = bundle.generic_edges
    else:
        st.caption(
            "Full network: exhaustive bus and LRU instances from Sender/Receiver. "
            "Orange = LRU · link colors: Low Power light red · High Power dark red · "
            "Analog brown · Discrete orange · Digital mono blue · "
            "Digital shared purple. Hardwired links are "
            "direct LRU↔LRU links (databus boxes only). "
            "Buses stay pinned; drag one bus at a time — connected LRUs re-settle."
        )
        nodes = bundle.graph_nodes
        edges = bundle.graph_edges

    c_m, c_s, c_a, c_d, c_lp, c_hp = st.columns(6)
    with c_m:
        show_mono = st.checkbox(
            "Digital mono",
            value=True,
            key="topo_show_mono",
            help="Show unidirectional digital databuses (blue).",
        )
    with c_s:
        show_shared = st.checkbox(
            "Digital shared",
            value=True,
            key="topo_show_shared",
            help="Show shared / multi-drop digital databuses (purple).",
        )
    with c_a:
        show_analog = st.checkbox(
            "Analog",
            value=False,
            key="topo_show_analog",
            help="Show direct Analog links from 1_Signals (Interfacing Equipment ≠ Owner).",
        )
    with c_d:
        show_discrete = st.checkbox(
            "Discrete",
            value=False,
            key="topo_show_discrete",
            help="Show direct Discrete links from 1_Signals (Interfacing Equipment ≠ Owner).",
        )
    with c_lp:
        show_low_power = st.checkbox(
            "Low Power",
            value=False,
            key="topo_show_low_power",
            help=(
                "Show direct Low Power (28 V supply network) links from 1_Signals "
                "(Interfacing Equipment ≠ Owner)."
            ),
        )
    with c_hp:
        show_high_power = st.checkbox(
            "High Power",
            value=False,
            key="topo_show_high_power",
            help=(
                "Show direct High Power (800 V traction network) links from "
                "1_Signals (Interfacing Equipment ≠ Owner)."
            ),
        )

    families = _bus_families(bundle.buses)
    family = st.selectbox(
        "Bus Definition",
        options=["(all)", *families],
        key="topo_family",
        help=(
            "Several bus instances can share one definition — the payload is "
            "authored once, on the tab of that name."
        ),
    )
    show_all = family == "(all)"

    plot_edges = edges if show_all else _edges_for_family(
        edges, nodes, bundle.buses, family
    )
    plot_edges = _filter_link_kinds(
        plot_edges,
        show_mono=show_mono,
        show_shared=show_shared,
        show_analog=show_analog,
        show_discrete=show_discrete,
        show_low_power=show_low_power,
        show_high_power=show_high_power,
    )
    # Nodes follow visible edges — toggling layers re-evaluates buses and LRUs.
    plot_nodes = _nodes_touched_by_edges(nodes, plot_edges)

    bus_options = sorted(
        plot_nodes.loc[plot_nodes["kind"].astype(str) == "bus", "node_id"]
        .astype(str)
        .unique()
        .tolist()
    ) if not plot_nodes.empty and "kind" in plot_nodes.columns else []
    lru_options = sorted(
        plot_nodes.loc[plot_nodes["kind"].astype(str) == "lru", "node_id"]
        .astype(str)
        .unique()
        .tolist()
    ) if not plot_nodes.empty and "kind" in plot_nodes.columns else []

    # Include layer toggles in widget keys so Bus/LRU multiselects reset to the
    # newly visible set whenever any layer filter changes.
    layer_key = (
        f"m{int(show_mono)}s{int(show_shared)}"
        f"a{int(show_analog)}d{int(show_discrete)}"
        f"lp{int(show_low_power)}hp{int(show_high_power)}"
    )

    with st.expander("Filter nodes on diagram", expanded=False):
        st.caption(
            "Choose which bus and LRU nodes to show. The lists update when link "
            "layer checkboxes change. Connections are kept only when both ends "
            "remain visible."
        )
        c1, c2 = st.columns(2)
        bus_key = f"topo_filter_buses_{view}_{family}_{layer_key}"
        lru_key = f"topo_filter_lrus_{view}_{family}_{layer_key}"
        pending_lru_key = f"{lru_key}__pending_expand"
        # Apply expansion before the multiselect widget is created (Streamlit rule).
        if pending_lru_key in st.session_state:
            pending = st.session_state.pop(pending_lru_key)
            st.session_state[lru_key] = [
                tok for tok in pending if tok in set(lru_options)
            ]
        with c1:
            bus_kwargs: dict = {"options": bus_options, "key": bus_key}
            if bus_key not in st.session_state:
                bus_kwargs["default"] = bus_options
            selected_buses = st.multiselect("Buses", **bus_kwargs)
        with c2:
            lru_kwargs: dict = {"options": lru_options, "key": lru_key}
            if lru_key not in st.session_state:
                lru_kwargs["default"] = lru_options
            selected_lrus = st.multiselect("LRUs", **lru_kwargs)
            if st.button(
                "Add linked LRUs (1 hop)",
                key=f"topo_add_linked_lrus_{view}_{family}_{layer_key}",
                help=(
                    "Add LRUs directly linked to the current selection on the "
                    "filtered graph: hardwired edges, or other LRUs "
                    "on the same visible databus (LRU–bus–LRU)."
                ),
                disabled=not selected_lrus or not lru_options,
            ):
                expanded = _lru_neighbors_one_hop(
                    list(selected_lrus),
                    plot_edges,
                    plot_nodes,
                    lru_universe=lru_options,
                )
                if expanded != list(selected_lrus):
                    st.session_state[pending_lru_key] = expanded
                    st.rerun()

    plot_nodes, plot_edges = _apply_node_filters(
        plot_nodes,
        plot_edges,
        selected_buses=selected_buses,
        selected_lrus=selected_lrus,
    )

    title = (
        ("Generic topology" if generic else "Bus topology")
        if show_all
        else f"{'Generic' if generic else 'Bus'} topology — {family}"
    )
    if group_by_function:
        title = f"{title} (by function)"
    if len(selected_buses) < len(bus_options) or len(selected_lrus) < len(lru_options):
        title = f"{title} (filtered)"

    render_draggable_bus_topology(
        plot_nodes,
        plot_edges,
        title=title,
        group_by_function=group_by_function,
        systems=bundle.systems,
        buses=bundle.buses,
        bus_payload=bundle.bus_payload,
        signals=bundle.signals,
    )

    if generic:
        st.subheader("Bus definitions")
        buses = bundle.buses
        if not show_all and not buses.empty and BUS_DEFINITION in buses.columns:
            buses = buses[buses[BUS_DEFINITION].astype(str) == family]
        # One row per definition for the summary table.
        if not buses.empty and BUS_DEFINITION in buses.columns:
            summary = (
                buses.groupby(BUS_DEFINITION, dropna=False)
                .agg(
                    instances=("Bus Id", "count"),
                    protocols=(
                        PROTOCOL,
                        lambda s: "; ".join(
                            sorted({str(x) for x in s if str(x).strip()})
                        ),
                    ),
                    topologies=(
                        TOPOLOGY,
                        lambda s: "; ".join(sorted({str(x) for x in s if str(x).strip()})),
                    ),
                )
                .reset_index()
            )
            if not show_all:
                summary = summary[summary[BUS_DEFINITION].astype(str) == family]
            show_dataframe(summary, height=220)
    else:
        st.subheader("Buses using this definition")
        buses = bundle.buses
        if not show_all and not buses.empty and BUS_DEFINITION in buses.columns:
            buses = buses[buses[BUS_DEFINITION].astype(str) == family]
        show_dataframe(
            buses[
                [
                    c
                    for c in [
                        "Bus Id",
                        BUS_NAME,
                        "Bus Definition",
                        "Bus description",
                        PROTOCOL,
                        TOPOLOGY,
                        "Sender",
                        "Receiver",
                    ]
                    if c in buses.columns
                ]
            ],
            height=260,
        )

    st.subheader("Data on this definition")
    payload = bundle.bus_payload
    if not show_all and not payload.empty:
        payload = payload[payload["definition_tab"].astype(str) == family]
    show_dataframe(
        payload[
            [
                c
                for c in [
                    "Allocation Id",
                    "definition_tab",
                    "Data name",
                    "Sender",
                    "Receiver",
                    "Signal Id",
                    "hop_role",
                ]
                if c in payload.columns
            ]
        ],
        height=320,
    )
