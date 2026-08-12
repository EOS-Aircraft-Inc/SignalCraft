"""Signals catalog edit mode (`1_Signals`)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from visualizer.components.filters import apply_text_search
from visualizer.components.instance_schema import render_containment_schema
from visualizer.components.selectors import (
    id_name_labels,
    labeled_acronym_select,
    labeled_multi_acronym,
    labeled_multi_select,
    labeled_select,
    system_acronym_labels,
    table_select_id,
)
from visualizer.data.loader import IcdBundle
from visualizer.data.models import INTERFACE_TYPES, SIGNAL_ID
from visualizer.edit_bridge import sparse_upsert
from visualizer.views.edit.common import render_apply_panel, sync_fields

SIGNAL_ROLES = ["Measurement", "Command", "Request", "Computed", "Power"]
EDITABLE_FIELDS = [
    "Physical Id",
    "Signal Name",
    "Signal Role",
    "Abbreviation",
    "Interfacing Equipment",
    "Signal Owner",
    "Repeated Per",
    "Related to",
    "Connection Type",
    "Interface Type",
    "Unit",
    "Functional Minimum",
    "Functional Maximum",
    "Derivation",
    "Notes",
    "On aircraft ?",
    "On FND ?",
    "On Sim ?",
]
_SEP = " — "


def _split_refs(value: str) -> list[str]:
    return [p.strip() for p in str(value or "").split(";") if p.strip()]


def _physical_id_labels(
    signals: pd.DataFrame,
) -> tuple[list[str], dict[str, str]]:
    """Unique Physical Id options labeled ``Id — Signal Name``."""
    labels: list[str] = []
    label_to_id: dict[str, str] = {}
    if signals.empty or "Physical Id" not in signals.columns:
        return labels, label_to_id
    seen: set[str] = set()
    for _, row in signals.iterrows():
        pid = str(row.get("Physical Id") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        name = str(row.get("Signal Name") or "").strip()
        label = f"{pid}{_SEP}{name}" if name else pid
        labels.append(label)
        label_to_id[label] = pid
    labels.sort()
    return labels, label_to_id


def render(bundle: IcdBundle) -> None:
    sheet = bundle.signals_sheet
    st.subheader(f"Signals (`{sheet}`)")
    st.caption(
        "Canonical signal catalog. Bus allocations reference these rows via "
        "`signal_id`. `Physical Id` is optional: use it only when two or more "
        "signals share the same physical meaning; leave blank otherwise."
    )
    signals = bundle.signals
    q = st.text_input("Search signals", key="edit_sig_q")
    view = apply_text_search(
        signals,
        q,
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
    st.caption("Click a row in the table to select it.")
    table_sid = table_select_id(view, SIGNAL_ID, key="edit_sig_table")
    if table_sid:
        st.session_state["edit_sig_selected_id"] = table_sid
        st.session_state["edit_sig_mode"] = "Edit existing"

    sid = str(st.session_state.get("edit_sig_selected_id") or "")
    if sid and sid not in set(signals[SIGNAL_ID].astype(str)):
        sid = ""
        st.session_state.pop("edit_sig_selected_id", None)

    sys_labels, sys_map = system_acronym_labels(bundle.systems)
    dim_labels, dim_map = system_acronym_labels(bundle.systems)
    phys_labels, phys_map = _physical_id_labels(signals)
    sig_labels, sig_map = id_name_labels(signals, SIGNAL_ID, "Signal Name")

    action = st.radio(
        "Action",
        ["Edit / Add", "Delete"],
        horizontal=True,
        key="edit_sig_action",
    )
    document: dict = {}

    if action == "Delete":
        if not sid:
            st.info("Select a signal row in the table to delete.")
        else:
            st.write(f"Delete **{sid}**?")
            document = {"delete": {sheet: [sid]}}
        render_apply_panel(document, key_prefix="edit_sig")
        return

    mode = st.radio(
        "Mode", ["Edit existing", "Add new"], horizontal=True, key="edit_sig_mode"
    )
    original: dict = {}
    current_related: list[str] = []

    if mode == "Edit existing":
        if not sid:
            st.info("Select a signal row in the table above.")
            render_apply_panel({}, key_prefix="edit_sig")
            return
        row = signals[signals[SIGNAL_ID] == sid].iloc[0]
        original = {c: str(row.get(c, "") or "") for c in signals.columns}
        st.markdown(
            f"**Selected:** `{sid}` — {original.get('Signal Name', '')} "
            f"({original.get('Signal Role', '')})"
        )
        acr_to_lab = {acr: lab for lab, acr in sys_map.items()}
        owner = str(original.get("Signal Owner") or "").strip()
        phys = str(original.get("Interfacing Equipment") or "").strip()
        repeated = _split_refs(original.get("Repeated Per", ""))
        known_signal_ids = set(sig_map.values())
        current_related = [
            ref
            for ref in _split_refs(original.get("Related to", ""))
            if ref in known_signal_ids and ref != sid
        ]
        phys_id_val = str(original.get("Physical Id") or "").strip()
        phys_to_lab = {v: lab for lab, v in phys_map.items()}
        related_labels = [
            lab for lab, rid in sig_map.items() if rid in current_related
        ]
        sync_fields(
            "edit_sig",
            sid,
            {
                "edit_sig_name": original.get("Signal Name", ""),
                "edit_sig_role": original.get("Signal Role", "") or "",
                "edit_sig_abbr": original.get("Abbreviation", ""),
                "edit_sig_phys_label": phys_to_lab.get(phys_id_val, ""),
                "edit_sig_owner_label": acr_to_lab.get(owner, ""),
                "edit_sig_psys_label": acr_to_lab.get(phys, ""),
                "edit_sig_rep": [acr_to_lab[a] for a in repeated if a in acr_to_lab],
                "edit_sig_related": related_labels,
                "edit_sig_conn": original.get("Connection Type", ""),
                "edit_sig_iface": original.get("Interface Type", ""),
                "edit_sig_unit": original.get("Unit", ""),
                "edit_sig_min": original.get("Functional Minimum", ""),
                "edit_sig_max": original.get("Functional Maximum", ""),
                "edit_sig_deriv": original.get("Derivation", ""),
                "edit_sig_notes": original.get("Notes", ""),
                "edit_sig_ac": original.get("On aircraft ?", ""),
                "edit_sig_fnd": original.get("On FND ?", ""),
                "edit_sig_sim": original.get("On Sim ?", ""),
            },
        )
    else:
        sid = st.text_input("Signal Id (blank = auto)", key="edit_sig_new")
        sync_fields(
            "edit_sig",
            "__new__",
            {
                "edit_sig_name": "",
                "edit_sig_role": "",
                "edit_sig_abbr": "",
                "edit_sig_phys_label": "",
                "edit_sig_owner_label": "",
                "edit_sig_psys_label": "",
                "edit_sig_rep": [],
                "edit_sig_related": [],
                "edit_sig_conn": "",
                "edit_sig_iface": "",
                "edit_sig_unit": "",
                "edit_sig_min": "",
                "edit_sig_max": "",
                "edit_sig_deriv": "",
                "edit_sig_notes": "",
                "edit_sig_ac": "",
                "edit_sig_fnd": "",
                "edit_sig_sim": "",
            },
        )

    name = st.text_input("Signal Name", key="edit_sig_name")
    role_col, abbr_col, pid_col = st.columns(3)
    with role_col:
        role_opts = [r for r in SIGNAL_ROLES if r]
        current_role = st.session_state.get("edit_sig_role", "")
        if current_role and current_role not in role_opts:
            role_opts = [*role_opts, current_role]
        role = st.selectbox(
            "Signal Role",
            options=[""] + role_opts,
            key="edit_sig_role",
        )
    with abbr_col:
        abbr = st.text_input("Abbreviation", key="edit_sig_abbr")
    with pid_col:
        phys_id = labeled_select(
            "Physical Id (only if shared)",
            phys_labels,
            phys_map,
            key="edit_sig_phys",
            current=str(original.get("Physical Id") or "")
            if mode == "Edit existing" and original
            else "",
        )

    owner_col, psys_col = st.columns(2)
    with owner_col:
        owner = labeled_acronym_select(
            "Signal Owner",
            sys_labels,
            sys_map,
            key="edit_sig_owner",
            current=str(original.get("Signal Owner") or "")
            if mode == "Edit existing" and original
            else "",
        )
    with psys_col:
        phys_sys = labeled_acronym_select(
            "Interfacing Equipment",
            sys_labels,
            sys_map,
            key="edit_sig_psys",
            current=str(original.get("Interfacing Equipment") or "")
            if mode == "Edit existing" and original
            else "",
        )
    if owner:
        render_containment_schema(bundle.systems, owner)

    repeated = labeled_multi_acronym(
        "Repeated Per",
        dim_labels,
        dim_map,
        key="edit_sig_rep",
        current=_split_refs(original.get("Repeated Per", ""))
        if mode == "Edit existing" and original
        else [],
    )

    related_options = [
        lab
        for lab, rid in sig_map.items()
        if not (mode == "Edit existing" and sid and rid == sid)
    ]
    related_map = {lab: sig_map[lab] for lab in related_options}
    related_ids = labeled_multi_select(
        "Related to signals (semicolon list)",
        related_options,
        related_map,
        key="edit_sig_related",
        current=current_related if mode == "Edit existing" else [],
    )
    related = ";".join(related_ids)

    conn_col, iface_col = st.columns(2)
    with conn_col:
        conn = st.text_input("Connection Type", key="edit_sig_conn")
    with iface_col:
        iface_opts = list(INTERFACE_TYPES)
        current_iface = (
            str(original.get("Interface Type") or "").strip()
            if mode == "Edit existing" and original
            else str(st.session_state.get("edit_sig_iface") or "")
        )
        if current_iface and current_iface not in iface_opts:
            iface_opts = [*iface_opts, current_iface]
        iface = st.selectbox(
            "Interface Type",
            options=[""] + iface_opts,
            key="edit_sig_iface",
        )

    unit = st.text_input("Unit", key="edit_sig_unit")
    min_col, max_col = st.columns(2)
    with min_col:
        minimum = st.text_input("Functional Minimum", key="edit_sig_min")
    with max_col:
        maximum = st.text_input("Functional Maximum", key="edit_sig_max")
    derivation = st.text_input("Derivation", key="edit_sig_deriv")
    notes = st.text_area("Notes", key="edit_sig_notes")
    ac_col, fnd_col, sim_col = st.columns(3)
    with ac_col:
        on_ac = st.text_input("On aircraft ?", key="edit_sig_ac")
    with fnd_col:
        on_fnd = st.text_input("On FND ?", key="edit_sig_fnd")
    with sim_col:
        on_sim = st.text_input("On Sim ?", key="edit_sig_sim")

    edited = {
        "Physical Id": phys_id,
        "Signal Name": name,
        "Signal Role": role,
        "Abbreviation": abbr,
        "Interfacing Equipment": phys_sys,
        "Signal Owner": owner,
        "Repeated Per": ";".join(repeated),
        "Related to": related,
        "Connection Type": conn,
        "Interface Type": iface,
        "Unit": unit,
        "Functional Minimum": minimum,
        "Functional Maximum": maximum,
        "Derivation": derivation,
        "Notes": notes,
        "On aircraft ?": on_ac,
        "On FND ?": on_fnd,
        "On Sim ?": on_sim,
    }
    edited = {k: v for k, v in edited.items() if k in EDITABLE_FIELDS}

    if mode == "Edit existing" and sid:
        patch = sparse_upsert(sheet, SIGNAL_ID, sid, original, edited)
        if patch:
            document = {"upsert": {sheet: [patch]}}
    elif mode == "Add new" and name:
        payload = {k: v for k, v in edited.items()}
        if sid:
            payload[SIGNAL_ID] = sid
        document = {"upsert": {sheet: [payload]}}

    render_apply_panel(document, key_prefix="edit_sig")
