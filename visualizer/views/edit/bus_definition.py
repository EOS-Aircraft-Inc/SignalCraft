"""Bus definition payload editor — Allocation Id + signal_id."""

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
from visualizer.data.models import ALLOCATION_ID, SIGNAL_ID
from visualizer.edit_bridge import sparse_upsert
from visualizer.views.edit.common import render_apply_panel, sync_fields


def _split_refs(value: str) -> list[str]:
    return [p.strip() for p in str(value or "").split(";") if p.strip()]


def render(bundle: IcdBundle) -> None:
    st.subheader("Bus definition (payload)")
    payload = bundle.bus_payload
    if payload.empty or "definition_tab" not in payload.columns:
        st.warning("No bus-definition payload rows loaded.")
        return

    tabs = sorted(
        {str(t).strip() for t in payload["definition_tab"].dropna() if str(t).strip()}
    )
    def_col = (
        "Bus Definition" if "Bus Definition" in bundle.buses.columns else "definition_tab"
    )
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
        [ALLOCATION_ID, "data_name", "signal_id", "writer_lru"],
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
            st.markdown(f"**Selected:** `{aid}` — {original.get('data_name', '')}")
            acr_to_lab = {acr: lab for lab, acr in sys_map.items()}
            writer = str(original.get("writer_lru") or "").strip()
            rx_refs = _split_refs(original.get("receiver_lrus", ""))
            signal_id = str(original.get("signal_id") or "").strip()
            sync_fields(
                "edit_pay",
                f"{sheet}:{aid}",
                {
                    "edit_pay_name": original.get("data_name", ""),
                    "edit_pay_wr_label": acr_to_lab.get(writer, ""),
                    "edit_pay_rx": [acr_to_lab[a] for a in rx_refs if a in acr_to_lab],
                    "edit_pay_sig_label": next(
                        (lab for lab, rid in sig_m.items() if rid == signal_id), ""
                    ),
                    "edit_pay_dim": original.get("instance_dimension", ""),
                    "edit_pay_enc": original.get("encoding", ""),
                    "edit_pay_unit": original.get("unit", ""),
                    "edit_pay_period": original.get("update_period_ms", ""),
                    "edit_pay_notes": original.get("notes", ""),
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
                    "edit_pay_enc": "",
                    "edit_pay_unit": "",
                    "edit_pay_period": "",
                    "edit_pay_notes": "",
                },
            )

        data_name = st.text_input("data_name", key="edit_pay_name")
        wr_col, rx_col = st.columns(2)
        with wr_col:
            writer = labeled_acronym_select(
                "writer_lru",
                sys_labels,
                sys_map,
                key="edit_pay_wr",
                current=str(original.get("writer_lru") or "")
                if mode == "Edit existing" and original
                else "",
            )
        with rx_col:
            receiver_list = labeled_multi_acronym(
                "receiver_lrus",
                sys_labels,
                sys_map,
                key="edit_pay_rx",
                current=_split_refs(original.get("receiver_lrus", ""))
                if mode == "Edit existing" and original
                else [],
            )
        if writer:
            render_containment_schema(bundle.systems, writer.split(";")[0].strip())

        signal_id = labeled_select(
            "signal_id",
            sig_l,
            sig_m,
            key="edit_pay_sig",
            current=str(original.get("signal_id") or "")
            if mode == "Edit existing" and original
            else "",
        )

        dim_col, enc_col = st.columns(2)
        with dim_col:
            dim = st.text_input("instance_dimension", key="edit_pay_dim")
        with enc_col:
            encoding = st.text_input("encoding", key="edit_pay_enc")
        unit_col, period_col = st.columns(2)
        with unit_col:
            unit = st.text_input("unit", key="edit_pay_unit")
        with period_col:
            period = st.text_input("update_period_ms", key="edit_pay_period")
        notes = st.text_area("notes", key="edit_pay_notes")

        edited = {
            "data_name": data_name,
            "writer_lru": writer,
            "receiver_lrus": ";".join(receiver_list),
            "signal_id": signal_id,
            "instance_dimension": dim,
            "encoding": encoding,
            "unit": unit,
            "update_period_ms": period,
            "notes": notes,
        }

        if mode == "Edit existing" and aid:
            patch = sparse_upsert(sheet, ALLOCATION_ID, aid, original, edited)
            if patch:
                document = {"upsert": {sheet: [patch]}}
        elif mode == "Add new" and data_name:
            payload_row = {k: v for k, v in edited.items()}
            if aid:
                payload_row[ALLOCATION_ID] = aid
            document = {"upsert": {sheet: [payload_row]}}

    render_apply_panel(document, key_prefix="edit_pay")
