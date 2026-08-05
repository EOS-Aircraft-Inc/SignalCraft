"""Shared dry-run / apply chrome for edit modes."""

from __future__ import annotations

from typing import Any

import streamlit as st

from visualizer.edit_bridge import apply_document, document_json, format_result


def sync_fields(load_key: str, row_id: str, fields: dict[str, str]) -> None:
    """When the selected row changes, copy field values into session_state.

    Streamlit ignores ``value=`` on widgets that already have a ``key``, so
    prefills must write session_state before the widgets are created.
    """
    marker = f"{load_key}__row"
    if st.session_state.get(marker) == row_id:
        return
    st.session_state[marker] = row_id
    for key, val in fields.items():
        st.session_state[key] = val


def apply_now(document: dict[str, Any], *, success: str = "Applied.") -> bool:
    """Write an edit document immediately; clear cache on success."""
    result = apply_document(document, dry_run=False)
    st.text(format_result(result))
    if result.ok:
        st.success(success)
        st.cache_data.clear()
        return True
    st.error("Preflight failed — nothing written.")
    return False


def render_apply_panel(document: dict[str, Any], *, key_prefix: str) -> None:
    if not document or (
        not document.get("upsert")
        and not document.get("delete")
        and not document.get("rewrite")
    ):
        st.info("No changes staged yet.")
        return

    with st.expander("Generated JSON", expanded=False):
        st.code(document_json(document), language="json")

    c1, c2 = st.columns(2)
    dry = c1.button("Dry-run", key=f"{key_prefix}_dry")
    apply = c2.button("Apply", type="primary", key=f"{key_prefix}_apply")

    if dry:
        result = apply_document(document, dry_run=True)
        st.text(format_result(result))
        if not result.ok:
            st.error("Preflight failed — nothing written.")
        else:
            st.info("Dry-run only — CSV not modified.")
    elif apply:
        if apply_now(document):
            st.rerun()
