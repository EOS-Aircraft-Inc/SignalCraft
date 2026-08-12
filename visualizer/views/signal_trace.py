"""Signal Trace page — follow a canonical SIG-* across bus allocations."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from visualizer.components.graphs import signal_trace_figure
from visualizer.components.selectors import id_name_labels, labeled_select
from visualizer.components.tables import show_dataframe
from visualizer.data.loader import IcdBundle, payloads_for_signal
from visualizer.data.models import ALLOCATION_ID, SIGNAL_ID


def _order_hops(hops: pd.DataFrame) -> pd.DataFrame:
    if hops.empty:
        return hops
    work = hops.copy()
    role_order = {
        "origin": 0,
        "command": 1,
        "request": 2,
        "computed": 3,
        "relay": 4,
        "other": 5,
        "unlinked": 6,
    }
    if "hop_role" in work.columns:
        work["_role_rank"] = work["hop_role"].map(lambda r: role_order.get(str(r), 9))
    else:
        work["_role_rank"] = 9
    sort_cols = ["_role_rank"]
    if ALLOCATION_ID in work.columns:
        sort_cols.append(ALLOCATION_ID)
    work = work.sort_values(sort_cols)
    return work.drop(columns=["_role_rank"], errors="ignore")


def render(bundle: IcdBundle) -> None:
    st.header("Signal Trace")
    st.caption(
        f"Start from a `{bundle.signals_sheet}` Signal Id. Every bus-definition "
        "allocation that carries the same `signal_id` is a hop (including relays). "
        "No duplicate signal rows are created for intermediate hops."
    )

    labels, label_to_id = id_name_labels(
        bundle.signals, SIGNAL_ID, "Signal Name"
    )
    signal_id = labeled_select(
        "Signal", labels, label_to_id, key="trace_signal"
    )
    if not signal_id:
        st.info("Select a Signal Id to trace.")
        return

    srow = bundle.signals[bundle.signals[SIGNAL_ID] == signal_id]
    if srow.empty:
        st.warning("Signal not found.")
        return
    row = srow.iloc[0]
    st.subheader("1. Signal definition")
    st.write(
        f"**{signal_id}** — {row.get('Signal Name', '')} — "
        f"**{row.get('Signal Role', '')}** — "
        f"{row.get('Interfacing Equipment', '')} / {row.get('Signal Owner', '')}"
    )
    if str(row.get("Repeated Per") or "").strip():
        st.caption(f"Repeated Per: `{row.get('Repeated Per')}`")
    if str(row.get("Related to") or "").strip():
        st.caption(f"Related to: `{row.get('Related to')}`")
    if str(row.get("Derivation") or "").strip():
        st.caption(str(row.get("Derivation", "")))

    st.subheader("2. Bus hops")
    hops = _order_hops(payloads_for_signal(bundle, signal_id=signal_id))
    if hops.empty:
        st.warning("No bus-definition allocations reference this Signal Id.")
        return

    for _, hop in hops.iterrows():
        alloc = hop.get(ALLOCATION_ID, "")
        st.markdown(
            f"- **{alloc}** — {hop.get('data_name', '')}  \n"
            f"  `{hop.get('writer_lru', '')}` → `{hop.get('receiver_lrus', '')}` "
            f"on `{hop.get('definition_tab', '')}` ({hop.get('hop_role', '')})"
        )

    st.plotly_chart(signal_trace_figure(hops), width="stretch")
    show_dataframe(
        hops[
            [
                c
                for c in [
                    ALLOCATION_ID,
                    "data_name",
                    "definition_tab",
                    "writer_lru",
                    "receiver_lrus",
                    "instance_dimension",
                    "signal_id",
                    "hop_role",
                    "notes",
                ]
                if c in hops.columns
            ]
        ],
        height=360,
    )
