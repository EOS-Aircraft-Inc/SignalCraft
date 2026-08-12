"""Bus definition payload editor — Allocation Id + Signal Id."""

from __future__ import annotations

import streamlit as st

from visualizer.components.filters import apply_text_search
from visualizer.components.instance_schema import render_containment_schema
from visualizer.components.selectors import (
    id_name_labels,
    labeled_acronym_select,
    labeled_multi_acronym,
    labeled_select,
    system_acronym_labels,
    table_select_id,
)
from visualizer.data.loader import IcdBundle
from visualizer.data.models import (
    ALLOCATION_ID,
    BUS_DEFINITION,
    SIGNAL_ID,
    split_refs,
)
from visualizer.edit_bridge import sparse_upsert
from visualizer.views.edit.common import render_apply_panel, sync_fields


def render(bundle: IcdBundle) -> None:
    st.subheader("Bus definition (payload)")
    st.caption(
        "One row per encoded item on a bus family. `Allocation Id` is unique "
        "across the whole workbook, and `Signal Id` points at exactly one row of "
        "`1_Signals` — a relay reuses the same `Signal Id` on each hop."
    )
    payload = bundle.bus_payload
    if payload.empty or "definition_tab" not in payload.columns:
        st.warning("No bus-definition payload rows loaded.")
        return

    tabs = sorted(
        {str(t).strip() for t in payload["definition_tab"].dropna() if str(t).strip()}
    )
    def_col = BUS_DEFINITION
    if def_col in bundle.buses.columns:
        for t in bundle.buses[def_col].dropna():
            t = str(t).strip()
            if t and t not in tabs:
                tabs.append(t)
        tabs = sorted(tabs)

    sheet = st.selectbox("Definition tab", options=tabs, key="edit_pay_tab")
    rows = payload[payload["definition_tab"] == sheet].copy()
    q = st.text_input("Search rows", key="edit_pay_q")
    view = apply_text_search(
        rows,
        q,
        [
            ALLOCATION_ID,
            "Data name",
            "Signal Id",
            "Sender",
            "Message ID",
            "Label",
        ],
    )
    st.caption("Click a row in the table to select it.")
    table_aid = table_select_id(view, ALLOCATION_ID, key=f"edit_pay_table_{sheet}")
    if table_aid:
        st.session_state["edit_pay_selected_id"] = table_aid
        st.session_state["edit_pay_mode"] = "Edit existing"

    aid = str(st.session_state.get("edit_pay_selected_id") or "")
    if aid and (rows.empty or aid not in set(rows[ALLOCATION_ID].astype(str))):
        aid = ""
        st.session_state.pop("edit_pay_selected_id", None)

    sys_labels, sys_map = system_acronym_labels(bundle.systems)
    sig_l, sig_m = id_name_labels(bundle.signals, SIGNAL_ID, "Signal Name")

    action = st.radio(
        "Action",
        ["Edit / Add", "Remove"],
        horizontal=True,
        key="edit_pay_action",
    )
    document: dict = {}

    if action == "Remove":
        if not aid:
            st.info("Select a payload row in the table to remove.")
        else:
            st.write(f"Remove **{aid}** from `{sheet}`?")
            document = {"delete": {sheet: [aid]}}
    else:
        mode = st.radio(
            "Mode", ["Edit existing", "Add new"], horizontal=True, key="edit_pay_mode"
        )
        original: dict = {}
        if mode == "Edit existing":
            if not aid:
                st.info("Select a payload row in the table above.")
                render_apply_panel({}, key_prefix="edit_pay")
                return
            row = rows[rows[ALLOCATION_ID] == aid].iloc[0]
            original = {c: str(row.get(c, "") or "") for c in rows.columns}
            st.markdown(f"**Selected:** `{aid}` — {original.get('Data name', '')}")
            acr_to_lab = {acr: lab for lab, acr in sys_map.items()}
            writer = str(original.get("Sender") or "").strip()
            rx_refs = split_refs(original.get("Receiver", ""))
            signal_id = str(original.get("Signal Id") or "").strip()
            sync_fields(
                "edit_pay",
                f"{sheet}:{aid}",
                {
                    "edit_pay_name": original.get("Data name", ""),
                    "edit_pay_wr_label": acr_to_lab.get(writer, ""),
                    "edit_pay_rx": [acr_to_lab[a] for a in rx_refs if a in acr_to_lab],
                    "edit_pay_sig_label": next(
                        (lab for lab, rid in sig_m.items() if rid == signal_id), ""
                    ),
                    "edit_pay_dim": original.get("instance_dimension", ""),
                    "edit_pay_msgid": original.get("Message ID", ""),
                    "edit_pay_msgname": original.get("Label", ""),
                    "edit_pay_startbit": original.get("start bit", ""),
                    "edit_pay_stopbit": original.get("stop bit", ""),
                    "edit_pay_enc": original.get("encoding", ""),
                    "edit_pay_unit": original.get("unit", ""),
                    "edit_pay_scale": original.get("scale", ""),
                    "edit_pay_res": original.get("resolution", ""),
                    "edit_pay_min": original.get("minimum", ""),
                    "edit_pay_max": original.get("maximum", ""),
                    "edit_pay_period": original.get("Refresh rate", ""),
                    "edit_pay_validity": original.get("validity", ""),
                    "edit_pay_notes": original.get("notes", ""),
                    "edit_pay_ac": original.get("On aircraft ?", ""),
                    "edit_pay_fnd": original.get("On FND ?", ""),
                    "edit_pay_sim": original.get("On Sim ?", ""),
                },
            )
        else:
            aid = st.text_input("Allocation Id (blank = auto)", key="edit_pay_new")
            sync_fields(
                "edit_pay",
                "__new__",
                {
                    "edit_pay_name": "",
                    "edit_pay_wr_label": "",
                    "edit_pay_rx": [],
                    "edit_pay_sig_label": "",
                    "edit_pay_dim": "",
                    "edit_pay_msgid": "",
                    "edit_pay_msgname": "",
                    "edit_pay_startbit": "",
                    "edit_pay_stopbit": "",
                    "edit_pay_enc": "",
                    "edit_pay_unit": "",
                    "edit_pay_scale": "",
                    "edit_pay_res": "",
                    "edit_pay_min": "",
                    "edit_pay_max": "",
                    "edit_pay_period": "",
                    "edit_pay_validity": "",
                    "edit_pay_notes": "",
                    "edit_pay_ac": "",
                    "edit_pay_fnd": "",
                    "edit_pay_sim": "",
                },
            )

        data_name = st.text_input("Data name", key="edit_pay_name")
        wr_col, rx_col = st.columns(2)
        with wr_col:
            writer = labeled_acronym_select(
                "Sender",
                sys_labels,
                sys_map,
                key="edit_pay_wr",
                current=str(original.get("Sender") or "")
                if mode == "Edit existing" and original
                else "",
            )
        with rx_col:
            receiver_list = labeled_multi_acronym(
                "Receiver",
                sys_labels,
                sys_map,
                key="edit_pay_rx",
                current=split_refs(original.get("Receiver", ""))
                if mode == "Edit existing" and original
                else [],
            )
        if writer:
            render_containment_schema(bundle.systems, writer.split(";")[0].strip())

        signal_id = labeled_select(
            "Signal Id",
            sig_l,
            sig_m,
            key="edit_pay_sig",
            current=str(original.get("Signal Id") or "")
            if mode == "Edit existing" and original
            else "",
        )

        dim = st.text_input(
            "instance_dimension",
            key="edit_pay_dim",
            help="Extra token when the bus instance alone is not enough, e.g. PACK-{n}.",
        )

        st.markdown("##### Transport")
        st.caption(
            "Every field below accepts `TBD` while the supplier design is open — "
            "these are working assumptions until the buses are frozen."
        )
        msgid_col, msgname_col = st.columns(2)
        with msgid_col:
            message_id = st.text_input(
                "Message ID",
                key="edit_pay_msgid",
                help="A825/CAN DOC or arbitration id, or the A429 label.",
            )
        with msgname_col:
            message_name = st.text_input(
                "Label", key="edit_pay_msgname",
                help="Human-readable message / frame name.",
            )
        startbit_col, stopbit_col = st.columns(2)
        with startbit_col:
            start_bit = st.text_input(
                "start bit", key="edit_pay_startbit", help="MSB of the field."
            )
        with stopbit_col:
            stop_bit = st.text_input(
                "stop bit", key="edit_pay_stopbit", help="LSB of the field, inclusive."
            )

        st.markdown("##### Encoding")
        enc_col, unit_col = st.columns(2)
        with enc_col:
            encoding = st.text_input("encoding", key="edit_pay_enc")
        with unit_col:
            unit = st.text_input("unit", key="edit_pay_unit")
        scale_col, res_col = st.columns(2)
        with scale_col:
            scale = st.text_input("scale", key="edit_pay_scale")
        with res_col:
            resolution = st.text_input("resolution", key="edit_pay_res")
        min_col, max_col = st.columns(2)
        with min_col:
            minimum = st.text_input(
                "minimum",
                key="edit_pay_min",
                help="Encoding range on this bus — often wider than the "
                "functional range on 1_Signals.",
            )
        with max_col:
            maximum = st.text_input("maximum", key="edit_pay_max")
        period_col, validity_col = st.columns(2)
        with period_col:
            period = st.text_input("Refresh rate", key="edit_pay_period")
        with validity_col:
            validity = st.text_input(
                "validity",
                key="edit_pay_validity",
                help="How the receiver judges the value is usable.",
            )

        notes = st.text_area("notes", key="edit_pay_notes")
        ac_col, fnd_col, sim_col = st.columns(3)
        with ac_col:
            on_ac = st.text_input("On aircraft ?", key="edit_pay_ac")
        with fnd_col:
            on_fnd = st.text_input("On FND ?", key="edit_pay_fnd")
        with sim_col:
            on_sim = st.text_input("On Sim ?", key="edit_pay_sim")

        edited = {
            "Data name": data_name,
            "Sender": writer,
            "Receiver": ";".join(receiver_list),
            "Signal Id": signal_id,
            "instance_dimension": dim,
            "Message ID": message_id,
            "Label": message_name,
            "start bit": start_bit,
            "stop bit": stop_bit,
            "encoding": encoding,
            "unit": unit,
            "scale": scale,
            "resolution": resolution,
            "minimum": minimum,
            "maximum": maximum,
            "Refresh rate": period,
            "validity": validity,
            "notes": notes,
            "On aircraft ?": on_ac,
            "On FND ?": on_fnd,
            "On Sim ?": on_sim,
        }

        if mode == "Edit existing" and aid:
            patch = sparse_upsert(sheet, ALLOCATION_ID, aid, original, edited)
            if patch:
                document = {"upsert": {sheet: [patch]}}
        elif mode == "Add new" and data_name:
            payload_row = dict(edited)
            if aid:
                payload_row[ALLOCATION_ID] = aid
            document = {"upsert": {sheet: [payload_row]}}

    render_apply_panel(document, key_prefix="edit_pay")
