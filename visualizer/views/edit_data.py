"""Edit data page — smart UI over the blind icd_edit JSON API."""

from __future__ import annotations

import streamlit as st

from visualizer.data.loader import IcdBundle
from visualizer.views.edit import bus_definition, databuses, signals, systems


def render(bundle: IcdBundle) -> None:
    st.header("Edit data")

    st.caption(
        "Guided editors build an upsert/delete/rewrite JSON document and run "
        "`icd_edit` dry-run / apply. Omitted fields are left unchanged; clear a "
        "field only by setting it empty explicitly. Use **Reload database** in "
        "the sidebar after an apply to refresh tables from csv/."
    )

    mode = st.radio(
        "Editor",
        [
            "System list",
            "Signals",
            "Databuses",
            "Bus definition",
        ],
        horizontal=True,
        key="edit_mode",
    )

    if mode == "System list":
        systems.render(bundle)
    elif mode == "Signals":
        signals.render(bundle)
    elif mode == "Databuses":
        databuses.render(bundle)
    else:
        bus_definition.render(bundle)
