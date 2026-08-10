"""System list edit mode."""

from __future__ import annotations

import streamlit as st

from visualizer.components.filters import apply_text_search
from visualizer.components.instance_schema import render_containment_schema
from visualizer.components.selectors import (
    labeled_acronym_select,
    system_acronym_labels,
    table_select_id,
)
from visualizer.data.loader import IcdBundle
from visualizer.data.models import (
    SYSTEM_ID,
    SYSTEM_TEXTUAL_NAME,
    SYSTEM_UNIQUE_ID,
    SYSTEMS_SHEET,
)
from visualizer.edit_bridge import sparse_upsert
from visualizer.views.edit.common import apply_now, render_apply_panel, sync_fields

STATUS_TYPES = ["Aircraft", "Zone", "Component", "Controller", "System"]
NO_INSTANCE_TYPES = frozenset({"Aircraft", "System"})


def _multiplicity_error(typ: str, mult: str, token: str = "") -> str | None:
    mult = (mult or "").strip()
    token = (token or "").strip()
    if typ in NO_INSTANCE_TYPES:
        if mult:
            return (
                f"Type '{typ}' must have an empty Multiplicity "
                "(functional / aircraft rows are not instantiated)."
            )
        return None
    if typ in {"Zone", "Component", "Controller"}:
        if not mult.isdigit() or int(mult) < 1:
            return (
                f"Type '{typ}' requires Multiplicity as a positive integer "
                f"(got {mult!r})."
            )
        if int(mult) > 1 and not token:
            return (
                f"Type '{typ}' with Multiplicity {mult} requires a non-empty "
                "Instance Token."
            )
    return None


def render(bundle: IcdBundle) -> None:
    st.subheader(f"System list (`{SYSTEMS_SHEET}`)")
    st.caption("Click a row in the table to select it.")
    systems = bundle.systems
    q = st.text_input("Search systems", key="edit_sys_q")
    view = apply_text_search(
        systems,
        q,
        [SYSTEM_UNIQUE_ID, SYSTEM_TEXTUAL_NAME, "Description"],
    )
    table_sid = table_select_id(view, SYSTEM_UNIQUE_ID, key="edit_sys_table")
    if table_sid:
        st.session_state["edit_sys_selected_id"] = table_sid
        st.session_state["edit_sys_mode"] = "Edit existing"

    sid = str(st.session_state.get("edit_sys_selected_id") or "")
    if sid and SYSTEM_UNIQUE_ID in systems.columns:
        if sid not in set(systems[SYSTEM_UNIQUE_ID].astype(str)):
            sid = ""
            st.session_state.pop("edit_sys_selected_id", None)
    elif sid:
        sid = ""

    action = st.radio(
        "Action",
        ["Edit / Add", "Delete"],
        horizontal=True,
        key="edit_sys_action",
    )
    document: dict = {}
    functional_labels, functional_map = system_acronym_labels(
        systems, include_types={"System"}
    )
    installed_labels, installed_map = system_acronym_labels(
        systems, exclude_types={"System"}
    )

    if action == "Delete":
        if not sid:
            st.info("Select a system row in the table to delete.")
        else:
            st.write(f"Delete **{sid}**?")
            document = {"delete": {SYSTEMS_SHEET: [sid]}}
        render_apply_panel(document, key_prefix="edit_sys")
        return

    mode = st.radio(
        "Mode", ["Edit existing", "Add new"], horizontal=True, key="edit_sys_mode"
    )
    original: dict = {}

    if mode == "Edit existing":
        if not sid:
            st.info("Select a system row in the table above.")
            return

        label_col, ren_col = st.columns([3, 1])
        with label_col:
            row0 = systems[systems[SYSTEM_UNIQUE_ID] == sid].iloc[0]
            st.markdown(
                f"**Selected:** `{sid}` — {row0.get(SYSTEM_TEXTUAL_NAME, '')}"
            )
        with ren_col:
            do_ren = st.button("Rename UniqueId", key="edit_sys_btn_ren_id")

        row = systems[systems[SYSTEM_UNIQUE_ID] == sid].iloc[0]
        original = {c: str(row.get(c, "") or "") for c in systems.columns}

        if do_ren:
            st.session_state["edit_sys_rename_mode"] = "id"
            st.session_state["edit_sys_rename_sid"] = sid

        rename_mode = st.session_state.get("edit_sys_rename_mode")
        rename_sid = st.session_state.get("edit_sys_rename_sid")
        if rename_mode == "id" and rename_sid == sid:
            st.markdown(f"Rename UniqueId **{sid}** (propagates to all references)")
            new_id = st.text_input("New UniqueId", key="edit_sys_inline_new_id")
            if st.button("Apply UniqueId rename", type="primary", key="edit_sys_apply_id"):
                if new_id.strip() and new_id.strip() != sid:
                    ok = apply_now(
                        {
                            "rewrite": {
                                "acronyms": [
                                    {"from": sid, "to": new_id.strip()}
                                ]
                            }
                        },
                        success=f"Renamed UniqueId {sid} -> {new_id.strip()}.",
                    )
                    if ok:
                        st.session_state["edit_sys_selected_id"] = new_id.strip()
                        st.session_state.pop("edit_sys_rename_mode", None)
                        st.rerun()
                else:
                    st.warning("Enter a different UniqueId.")
            if st.button("Cancel rename", key="edit_sys_cancel_ren"):
                st.session_state.pop("edit_sys_rename_mode", None)
                st.rerun()

        func_acr = str(original.get("Functional system") or "").strip()
        inst_acr = str(original.get("Installed In/Part of") or "").strip()
        func_label = next(
            (lab for lab, a in functional_map.items() if a == func_acr), ""
        )
        inst_label = next(
            (lab for lab, a in installed_map.items() if a == inst_acr), ""
        )
        sync_fields(
            "edit_sys",
            sid,
            {
                "edit_sys_name": original.get(SYSTEM_TEXTUAL_NAME, ""),
                "edit_sys_type": original.get("Type", "")
                if original.get("Type") in STATUS_TYPES
                else "",
                "edit_sys_func_label": func_label,
                "edit_sys_inst_label": inst_label,
                "edit_sys_mult": original.get("Multiplicity", ""),
                "edit_sys_tok": original.get("Instance Token", ""),
                "edit_sys_desc": original.get("Description", ""),
                "edit_sys_notes": original.get("Notes", ""),
            },
        )
    else:
        st.session_state.pop("edit_sys_rename_mode", None)
        sid = st.text_input("UniqueId (required)", key="edit_sys_new_id")
        sync_fields(
            "edit_sys",
            "__new__",
            {
                "edit_sys_name": "",
                "edit_sys_type": "",
                "edit_sys_func_label": "",
                "edit_sys_inst_label": "",
                "edit_sys_mult": "",
                "edit_sys_tok": "",
                "edit_sys_desc": "",
                "edit_sys_notes": "",
            },
        )

    name = st.text_input("Textual Name", key="edit_sys_name")

    type_options = [""] + STATUS_TYPES
    type_col, func_col = st.columns(2)
    with type_col:
        typ = st.selectbox("Type", type_options, key="edit_sys_type")
    no_instance = typ in NO_INSTANCE_TYPES
    with func_col:
        if no_instance:
            functional = ""
            st.caption("Functional system: empty for Aircraft / System.")
        else:
            functional = labeled_acronym_select(
                "Functional system",
                functional_labels,
                functional_map,
                key="edit_sys_func",
                current=str(original.get("Functional system") or "")
                if mode == "Edit existing" and original
                else "",
            )

    if no_instance:
        installed = ""
        mult = ""
        token = ""
        st.caption(
            "Type **Aircraft** or **System** (functional): Installed In, "
            "Multiplicity and Instance Token stay empty."
        )
    else:
        installed = labeled_acronym_select(
            "Installed In/Part of",
            installed_labels,
            installed_map,
            key="edit_sys_inst",
            current=str(original.get("Installed In/Part of") or "")
            if mode == "Edit existing" and original
            else "",
        )
        mult_col, tok_col = st.columns(2)
        with mult_col:
            mult = st.text_input("Multiplicity", key="edit_sys_mult")
        with tok_col:
            token = st.text_input("Instance Token", key="edit_sys_tok")

    preview_id = sid.strip() if mode == "Add new" else sid
    render_containment_schema(
        systems,
        preview_id,
        overrides={
            SYSTEM_UNIQUE_ID: preview_id,
            SYSTEM_TEXTUAL_NAME: name,
            "Type": typ or "",
            "Installed In/Part of": installed,
            "Multiplicity": mult,
            "Instance Token": token,
        },
    )

    desc = st.text_area("Description", key="edit_sys_desc")
    notes = st.text_area("Notes", key="edit_sys_notes")

    mult_err = _multiplicity_error(typ or "", mult, token)
    if mult_err:
        st.error(mult_err)

    with_buses_choice = "(auto-detect / required)"
    if not no_instance:
        with_buses_choice = st.radio(
            "If multiplicity impacts buses",
            ["(auto-detect / required)", "with_buses=true", "with_buses=false"],
            key="edit_sys_buses",
        )

    edited = {
        SYSTEM_TEXTUAL_NAME: name,
        "Type": typ or "",
        "Description": desc,
        "Notes": notes,
        "Installed In/Part of": installed,
        "Functional system": functional,
        "Multiplicity": mult,
        "Instance Token": token,
    }
    if mode == "Add new":
        payload = {k: v for k, v in edited.items() if v != ""}
        if no_instance:
            payload.pop("Installed In/Part of", None)
            payload.pop("Functional system", None)
            payload.pop("Multiplicity", None)
            payload.pop("Instance Token", None)
        if sid.strip():
            payload[SYSTEM_UNIQUE_ID] = sid.strip()
        if sid.strip() and (name or typ) and not mult_err:
            document = {"upsert": {SYSTEMS_SHEET: [payload]}}
        elif (name or typ) and not sid.strip():
            st.warning("UniqueId is required for new systems.")
    elif sid and not mult_err:
        patch = sparse_upsert(SYSTEMS_SHEET, SYSTEM_ID, sid, original, edited)
        if patch:
            document = {"upsert": {SYSTEMS_SHEET: [patch]}}

    if document and with_buses_choice.endswith("true"):
        document["options"] = {"with_buses": True}
    elif document and with_buses_choice.endswith("false"):
        document["options"] = {"with_buses": False}

    render_apply_panel(document, key_prefix="edit_sys")
