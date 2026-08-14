"""Bus Explorer page — browse generic bus definitions and their allocations."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from visualizer.components.filters import apply_text_search
from visualizer.components.graphs import bus_instance_figure
from visualizer.components.selectors import labeled_select
from visualizer.components.tables import show_dataframe
from visualizer.data.bus_instances import build_bus_instance_graph
from visualizer.data.loader import IcdBundle
from visualizer.data.models import (
    ALLOCATION_ID,
    BUS_DEFINITION,
    BUS_NAME,
    ENCODING,
    INSTANCE_DIMENSION,
    MESSAGE_ID,
    NOTES,
    PROTOCOL,
    REFRESH_PERIOD_MS,
    SIGNAL_ID,
    SPEED,
    START_BIT,
    STOP_BIT,
    TOPOLOGY,
    UNIT,
)


def _definition_column(buses: pd.DataFrame) -> str:
    """The bus sheet's own column. Allocation rows use ``definition_tab``."""
    return BUS_DEFINITION if BUS_DEFINITION in buses.columns else ""


def _generic_bus_summary(buses: pd.DataFrame, payload: pd.DataFrame) -> pd.DataFrame:
    """One row per Bus Definition with instance count and allocation count."""
    col = _definition_column(buses)
    if not col or buses.empty:
        return pd.DataFrame()

    def _join_unique(series: pd.Series) -> str:
        values = sorted({str(v).strip() for v in series if str(v).strip()})
        return "; ".join(values)

    agg: dict[str, tuple[str, object]] = {}
    if "Bus Id" in buses.columns:
        agg["instances"] = ("Bus Id", "count")
    else:
        agg["instances"] = (col, "count")
    if PROTOCOL in buses.columns:
        agg["protocols"] = (PROTOCOL, _join_unique)
    if TOPOLOGY in buses.columns:
        agg["topologies"] = (TOPOLOGY, _join_unique)
    if BUS_NAME in buses.columns:
        agg["names"] = (BUS_NAME, _join_unique)

    summary = (
        buses.groupby(col, dropna=False)
        .agg(**agg)
        .reset_index()
        .rename(columns={col: "Bus Definition"})
    )

    if not payload.empty and "definition_tab" in payload.columns:
        counts = (
            payload.groupby("definition_tab", dropna=False)
            .size()
            .rename("allocations")
            .reset_index()
            .rename(columns={"definition_tab": "Bus Definition"})
        )
        summary = summary.merge(counts, on="Bus Definition", how="left")
        summary["allocations"] = summary["allocations"].fillna(0).astype(int)
    else:
        summary["allocations"] = 0

    return summary.sort_values("Bus Definition").reset_index(drop=True)


def _enrich_payload(payload: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    if payload.empty:
        return payload
    work = payload.copy()
    if signals.empty or SIGNAL_ID not in signals.columns or SIGNAL_ID not in work.columns:
        return work
    cols = [SIGNAL_ID]
    for optional in ("Signal Name", "Signal Role", "Abbreviation"):
        if optional in signals.columns:
            cols.append(optional)
    lookup = signals[cols].drop_duplicates(SIGNAL_ID)
    # Allocations and the signals catalog now share the Signal Id column name,
    # so this is a plain same-key join.
    return work.merge(lookup, on=SIGNAL_ID, how="left", suffixes=("", "_sig"))


def render(bundle: IcdBundle) -> None:
    st.header("Bus Explorer")
    st.caption(
        "Browse generic bus definitions (`Bus Definition` / definition tabs). "
        "Select one to see physical instances from `10_Databuses` and the data "
        "allocated on that bus family."
    )

    buses = bundle.buses
    payload = bundle.bus_payload
    summary = _generic_bus_summary(buses, payload)
    if summary.empty:
        st.warning("No bus definitions loaded.")
        return

    col_select, col_search = st.columns([1.2, 1.8])
    with col_search:
        query = st.text_input("Search bus definitions", key="bus_explorer_search")
    view = apply_text_search(
        summary,
        query,
        ["Bus Definition", "names", "protocols", "topologies"],
    )

    options = view["Bus Definition"].astype(str).tolist()
    labels = {
        name: (
            f"{name} ({int(row.allocations)} alloc, {int(row.instances)} inst)"
            if "allocations" in view.columns and "instances" in view.columns
            else name
        )
        for name, row in view.set_index("Bus Definition").iterrows()
    }
    with col_select:
        selected = labeled_select(
            "Select Bus Definition",
            [labels.get(o, o) for o in options],
            {labels.get(o, o): o for o in options},
            key="bus_explorer_def",
        )

    if selected:
        _render_selection(bundle, summary, selected)
    else:
        st.info("Select a Bus Definition for details.")

    st.subheader("Generic buses")
    show_dataframe(
        view[
            [
                c
                for c in [
                    "Bus Definition",
                    "instances",
                    "allocations",
                    "protocols",
                    "topologies",
                    "names",
                ]
                if c in view.columns
            ]
        ],
        height=420,
    )

    if selected:
        st.subheader(f"{selected} — instances and connected LRUs")
        graph = build_bus_instance_graph(buses, selected, bundle.systems)
        if graph.instances:
            st.caption(
                f"{len(graph.instances)} bus instance(s): {', '.join(graph.instances)}"
            )
        st.plotly_chart(bus_instance_figure(graph), width="stretch")


def _render_selection(bundle: IcdBundle, summary: pd.DataFrame, selected: str) -> None:
    """Instance and allocation tables for the selected Bus Definition."""
    buses = bundle.buses
    payload = bundle.bus_payload

    st.subheader(selected)
    meta = summary[summary["Bus Definition"].astype(str) == selected]
    if not meta.empty:
        row = meta.iloc[0]
        st.caption(
            f"{int(row.get('instances', 0))} instance(s) · "
            f"{int(row.get('allocations', 0))} allocation(s) · "
            f"{row.get('protocols', '')} · {row.get('topologies', '')}"
        )

    st.markdown("**Physical instances**")
    def_col = _definition_column(buses)
    instances = (
        buses[buses[def_col].astype(str) == selected]
        if def_col and not buses.empty
        else buses.iloc[0:0]
    )
    show_dataframe(
        instances[
            [
                c
                for c in [
                    "Bus Id",
                    BUS_NAME,
                    "Bus description",
                    PROTOCOL,
                    SPEED,
                    TOPOLOGY,
                    "Sender",
                    "Receiver",
                ]
                if c in instances.columns
            ]
        ],
        height=200,
    )

    st.markdown("**Data on this bus**")
    family_payload = (
        payload[payload["definition_tab"].astype(str) == selected]
        if not payload.empty and "definition_tab" in payload.columns
        else payload.iloc[0:0]
    )
    enriched = _enrich_payload(family_payload, bundle.signals)
    show_dataframe(
        enriched[
            [
                c
                for c in [
                    ALLOCATION_ID,
                    "Data name",
                    "Signal Id",
                    "Signal Name",
                    "Signal Role",
                    "Sender",
                    "Receiver",
                    INSTANCE_DIMENSION,
                    MESSAGE_ID,
                    "Label",
                    START_BIT,
                    STOP_BIT,
                    ENCODING,
                    UNIT,
                    REFRESH_PERIOD_MS,
                    "hop_role",
                    NOTES,
                ]
                if c in enriched.columns
            ]
        ],
        height=420,
    )
