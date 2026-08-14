"""Databuses topology edit mode."""

from __future__ import annotations

import streamlit as st

from visualizer.components.selectors import (
    filter_buses_by_acronym,
    instance_endpoint_labels,
    labeled_acronym_select,
    labeled_multi_select,
    system_acronym_labels,
    table_select_id,
)
from visualizer.data.loader import IcdBundle
from visualizer.data.models import (
    BUS_DEFINITION,
    BUS_ID,
    BUS_NAME,
    BUS_TOPOLOGIES,
    DATABUSES_SHEET,
    PROTOCOL,
    SPEED,
    TOPOLOGY,
    split_refs,
)
from visualizer.edit_bridge import sparse_upsert
from visualizer.views.edit.common import render_apply_panel, sync_fields

# Generic topology LRUs: physical equipment that rides Sender/Receiver.
_GENERIC_TYPES = frozenset({"Component"})


def _def_col(buses) -> str:
    """The bus sheet's own Bus Definition column."""
    return BUS_DEFINITION


def render(bundle: IcdBundle) -> None:
    st.subheader(f"Databuses (`{DATABUSES_SHEET}`)")
    st.caption(
        "Topology index only — payload rows are edited under Bus definition. "
        "Pick a component to list every bus where any of its instances is "
        "Sender or Receiver. Click a row to select it."
    )
    buses = bundle.buses
    comp_labels, comp_map = system_acronym_labels(
        bundle.systems, include_types=_GENERIC_TYPES
    )
    # Tokens already present on any bus — keep odd/legacy values selectable.
    bus_tokens: list[str] = []
    for col in ("Sender", "Receiver"):
        if col not in buses.columns:
            continue
        for value in buses[col].dropna():
            bus_tokens.extend(split_refs(str(value)))
    endpoint_labels, endpoint_map = instance_endpoint_labels(
        bundle.systems, extra_tokens=bus_tokens
    )

    component = labeled_acronym_select(
        "Component",
        comp_labels,
        comp_map,
        key="edit_bus_comp",
    )
    if component:
        view = filter_buses_by_acronym(buses, component)
        st.caption(
            f"Buses involving any instance of **{component}** "
            f"({len(view)} of {len(buses)})."
        )
    else:
        view = buses
        st.caption("No component filter — showing all buses.")

    table_bid = table_select_id(view, "Bus Id", key="edit_bus_table")
    if table_bid:
        st.session_state["edit_bus_selected_id"] = table_bid
        st.session_state["edit_bus_mode"] = "Edit existing"

    bid = str(st.session_state.get("edit_bus_selected_id") or "")
    if bid and (buses.empty or bid not in set(buses["Bus Id"].astype(str))):
        bid = ""
        st.session_state.pop("edit_bus_selected_id", None)

    def_col = _def_col(buses)
    families = sorted(
        {
            str(v).strip()
            for v in buses[def_col].dropna()
            if str(v).strip()
        }
        if def_col in buses.columns
        else []
    )

    action = st.radio(
        "Action",
        ["Edit / Add", "Delete"],
        horizontal=True,
        key="edit_bus_action",
    )
    document: dict = {}

    if action == "Delete":
        if not bid:
            st.info("Select a bus row in the table to delete.")
        else:
            st.write(f"Delete **{bid}**?")
            document = {"delete": {DATABUSES_SHEET: [bid]}}
    else:
        mode = st.radio(
            "Mode", ["Edit existing", "Add new"], horizontal=True, key="edit_bus_mode"
        )
        original: dict = {}
        if mode == "Edit existing":
            if not bid:
                st.info("Select a bus row in the table above.")
                render_apply_panel({}, key_prefix="edit_bus")
                return
            row = buses[buses["Bus Id"] == bid].iloc[0]
            original = {c: str(row.get(c, "") or "") for c in buses.columns}
            st.markdown(f"**Selected:** `{bid}` — {original.get('name', '')}")
            ep_to_lab = {val: lab for lab, val in endpoint_map.items()}
            wr_refs = split_refs(original.get("Sender", ""))
            rx_refs = split_refs(original.get("Receiver", ""))
            sync_fields(
                "edit_bus",
                bid,
                {
                    "edit_bus_name": original.get(BUS_NAME, ""),
                    "edit_bus_def": original.get(def_col, "")
                    if original.get(def_col) in families
                    else "",
                    "edit_bus_wr": [
                        ep_to_lab[t] for t in wr_refs if t in ep_to_lab
                    ],
                    "edit_bus_rx": [
                        ep_to_lab[t] for t in rx_refs if t in ep_to_lab
                    ],
                    "edit_bus_proto": original.get(PROTOCOL, ""),
                    "edit_bus_speed": original.get(SPEED, ""),
                    "edit_bus_topo": original.get(TOPOLOGY, ""),
                    "edit_bus_use": original.get("Bus description", ""),
                    "edit_bus_ac": original.get("On aircraft ?", ""),
                    "edit_bus_fnd": original.get("On FND ?", ""),
                    "edit_bus_sim": original.get("On Sim ?", ""),
                },
            )
        else:
            bid = st.text_input("Bus Id", key="edit_bus_new_id")
            sync_fields(
                "edit_bus",
                "__new__",
                {
                    "edit_bus_name": "",
                    "edit_bus_def": "",
                    "edit_bus_wr": [],
                    "edit_bus_rx": [],
                    "edit_bus_proto": "",
                    "edit_bus_speed": "",
                    "edit_bus_topo": "",
                    "edit_bus_use": "",
                    "edit_bus_ac": "",
                    "edit_bus_fnd": "",
                    "edit_bus_sim": "",
                },
            )

        name = st.text_input(BUS_NAME, key="edit_bus_name")
        def_col_ui, proto_col = st.columns(2)
        with def_col_ui:
            definition = st.selectbox(
                "Bus Definition / family",
                ["", *families, "(new…)"],
                key="edit_bus_def",
            )
        with proto_col:
            protocol = st.text_input(PROTOCOL, key="edit_bus_proto")
        if definition == "(new…)":
            definition = st.text_input("New definition tab name", key="edit_bus_def_new")

        speed_col, topo_col = st.columns(2)
        with speed_col:
            speed = st.text_input(SPEED, key="edit_bus_speed")
        with topo_col:
            topo_opts = list(BUS_TOPOLOGIES)
            current_topo = (
                str(original.get(TOPOLOGY) or "").strip()
                if mode == "Edit existing" and original
                else str(st.session_state.get("edit_bus_topo") or "")
            )
            if current_topo and current_topo not in topo_opts:
                topo_opts = [*topo_opts, current_topo]
            topology = st.selectbox(
                TOPOLOGY,
                options=["", *topo_opts],
                key="edit_bus_topo",
                help=(
                    "Unidirectional / Shared for digital buses; "
                    "Analog / Discrete / Low Power / High Power for non-digital links."
                ),
            )

        wr_col, rx_col = st.columns(2)
        with wr_col:
            writer_list = labeled_multi_select(
                "Sender",
                endpoint_labels,
                endpoint_map,
                key="edit_bus_wr",
                current=split_refs(original.get("Sender", ""))
                if mode == "Edit existing" and original
                else [],
            )
        with rx_col:
            receiver_list = labeled_multi_select(
                "Receiver",
                endpoint_labels,
                endpoint_map,
                key="edit_bus_rx",
                current=split_refs(original.get("Receiver", ""))
                if mode == "Edit existing" and original
                else [],
            )
        bus_use = st.text_area("Bus description", key="edit_bus_use")
        ac_col, fnd_col, sim_col = st.columns(3)
        with ac_col:
            on_ac = st.text_input("On aircraft ?", key="edit_bus_ac")
        with fnd_col:
            on_fnd = st.text_input("On FND ?", key="edit_bus_fnd")
        with sim_col:
            on_sim = st.text_input("On Sim ?", key="edit_bus_sim")

        edited = {
            BUS_NAME: name,
            def_col: definition,
            "Sender": ";".join(writer_list),
            "Receiver": ";".join(receiver_list),
            PROTOCOL: protocol,
            SPEED: speed,
            TOPOLOGY: topology,
            "Bus description": bus_use,
            "On aircraft ?": on_ac,
            "On FND ?": on_fnd,
            "On Sim ?": on_sim,
        }

        if mode == "Edit existing" and bid:
            patch = sparse_upsert(DATABUSES_SHEET, BUS_ID, bid, original, edited)
            if patch:
                document = {"upsert": {DATABUSES_SHEET: [patch]}}
        elif mode == "Add new" and bid:
            payload = {k: v for k, v in edited.items() if v != ""}
            payload["Bus Id"] = bid
            document = {"upsert": {DATABUSES_SHEET: [payload]}}

    render_apply_panel(document, key_prefix="edit_bus")
