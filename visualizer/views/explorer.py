"""Signal Explorer page — browse the canonical signals catalog."""

from __future__ import annotations

import streamlit as st

from visualizer.components.filters import apply_text_search, filter_by_systems, system_filter
from visualizer.components.selectors import id_name_labels, labeled_select
from visualizer.components.tables import show_dataframe
from visualizer.data.loader import IcdBundle, payloads_for_signal
from visualizer.data.models import ALLOCATION_ID, SIGNAL_ID


def render(bundle: IcdBundle) -> None:
    st.header("Signal Explorer")
    st.caption(
        f"Browse `{bundle.signals_sheet}` — one row per logical signal. "
        "Bus allocations are linked by canonical `signal_id`. "
        "`Repeated Per` adds dimensions beyond those implied by Signal Owner / "
        "Interfacing Equipment; empty means every instance of the base system."
    )

    query = st.text_input("Search", key="explorer_search")
    owner_col = "Signal Owner" if "Signal Owner" in bundle.signals.columns else None
    signals = bundle.signals
    if owner_col:
        systems = system_filter(
            signals.rename(columns={owner_col: "System"}),
            key="explorer_sys",
            systems=bundle.systems,
        )
        work = filter_by_systems(
            signals.rename(columns={owner_col: "System"}), systems
        ).rename(columns={"System": owner_col})
    else:
        work = signals

    work = apply_text_search(
        work,
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

    col_table, col_detail = st.columns([1.4, 1])
    with col_table:
        st.subheader("Signals")
        show_dataframe(
            work[
                [
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
            ]
        )
        ids_l, ids_m = id_name_labels(work, SIGNAL_ID, "Signal Name")
        selected = labeled_select(
            "Select Signal Id",
            ids_l,
            ids_m,
            key="explorer_sig",
        )

    with col_detail:
        if not selected:
            st.info("Select a Signal Id for details.")
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

        linked = payloads_for_signal(bundle, signal_id=selected)
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
