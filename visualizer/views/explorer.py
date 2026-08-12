"""Signal Explorer page — browse the canonical signals catalog."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from visualizer.components.filters import apply_text_search, filter_by_systems, system_filter
from visualizer.components.graphs import signal_dataflow_figure
from visualizer.components.tables import show_aggrid, show_dataframe
from visualizer.data.dataflow import build_dataflow
from visualizer.data.loader import IcdBundle, payloads_for_signal
from visualizer.data.models import ALLOCATION_ID, SIGNAL_ID

_HOP_ROLE_ORDER = {
    "origin": 0,
    "command": 1,
    "request": 2,
    "computed": 3,
    "relay": 4,
    "other": 5,
    "unlinked": 6,
}


def _order_hops(hops: pd.DataFrame) -> pd.DataFrame:
    """Order allocations the way the signal actually flows."""
    if hops.empty:
        return hops
    work = hops.copy()
    if "hop_role" in work.columns:
        work["_role_rank"] = work["hop_role"].map(lambda r: _HOP_ROLE_ORDER.get(str(r), 9))
    else:
        work["_role_rank"] = 9
    sort_cols = ["_role_rank"]
    if ALLOCATION_ID in work.columns:
        sort_cols.append(ALLOCATION_ID)
    work = work.sort_values(sort_cols)
    return work.drop(columns=["_role_rank"], errors="ignore")


def render(bundle: IcdBundle) -> None:
    st.header("Signal Explorer")
    st.caption(
        f"Browse `{bundle.signals_sheet}` — one row per logical signal. "
        "Bus allocations are linked by canonical `signal_id`. "
        "`Repeated Per` adds dimensions beyond those implied by Signal Owner / "
        "Interfacing Equipment; empty means every instance of the base system."
    )

    # A system matters as either end of the interface, so filter on both.
    system_cols = [
        c for c in ["Signal Owner", "Interfacing Equipment"] if c in bundle.signals.columns
    ]

    col_system, col_search = st.columns([1.4, 1])
    with col_system:
        systems = system_filter(
            bundle.signals,
            system_cols,
            key="explorer_sys",
            systems=bundle.systems,
        )
    with col_search:
        query = st.text_input("Search", key="explorer_search")

    work = apply_text_search(
        filter_by_systems(bundle.signals, systems, system_cols),
        query,
        [
            SIGNAL_ID,
            "Signal Name",
            "Abbreviation",
            "Physical Id",
            "Interfacing Equipment",
            "Signal Owner",
            "Signal Role",
            "Notes",
        ],
    )

    table_cols = [
        c
        for c in [
            SIGNAL_ID,
            "Signal Name",
            "Signal Role",
            "Physical Id",
            "Interfacing Equipment",
            "Signal Owner",
            "Repeated Per",
            "Abbreviation",
        ]
        if c in work.columns
    ]

    st.subheader("Signals")
    selected = show_aggrid(work[table_cols], key="explorer_grid", selection_column=SIGNAL_ID)

    st.divider()
    if not selected:
        st.info("Click a signal row for details.")
        return

    st.subheader(selected)
    srow = bundle.signals[bundle.signals[SIGNAL_ID] == selected]
    if srow.empty:
        st.warning("Signal not found.")
        return
    row = srow.iloc[0]
    st.write(row.get("Signal Name", ""))
    st.caption(
        f"{row.get('Signal Role', '')} · Physical `{row.get('Physical Id', '')}` · "
        f"{row.get('Interfacing Equipment', '')} ↔ {row.get('Signal Owner', '')}"
    )
    if str(row.get("Related to") or "").strip():
        st.write(f"Related to: `{row.get('Related to')}`")
    if str(row.get("Notes") or "").strip():
        st.write(row.get("Notes", ""))

    st.markdown("**Dataflow**")
    flow = build_dataflow(bundle, selected)
    relatives = [s for s in flow.signal_ids if s != selected]
    if relatives:
        st.caption(
            "Dotted legs come from signals merged in via `Related to` / "
            f"`Physical Id`: {', '.join(relatives)}"
        )
    st.plotly_chart(signal_dataflow_figure(flow), width="stretch")

    linked = _order_hops(payloads_for_signal(bundle, signal_id=selected))
    st.markdown("**Bus allocations**")
    if linked.empty:
        st.info("No bus-definition allocations reference this Signal Id.")
    else:
        show_dataframe(
            linked[
                [
                    c
                    for c in [
                        ALLOCATION_ID,
                        "definition_tab",
                        "data_name",
                        "writer_lru",
                        "receiver_lrus",
                        "instance_dimension",
                        "signal_id",
                        "hop_role",
                    ]
                    if c in linked.columns
                ]
            ],
            height=280,
        )
