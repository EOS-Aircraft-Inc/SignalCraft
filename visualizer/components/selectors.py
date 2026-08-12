"""Labeled entity pickers for the Edit data UI.

External references display as ``UniqueId — Textual Name`` and widgets
return bare UniqueIds for persistence. Filter text boxes are opt-in
(``with_filter=True``) — do not add them by default.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from icd_instances import SystemTree

from visualizer.data.models import (
    RECEIVER,
    SENDER,
    SYSTEM_TEXTUAL_NAME,
    SYSTEM_UNIQUE_ID,
)

_SEP = " — "


def id_name_labels(
    frame: pd.DataFrame, id_col: str, name_col: str
) -> tuple[list[str], dict[str, str]]:
    """Build ``Id — Name`` labels mapped back to bare ids."""
    labels: list[str] = []
    label_to_id: dict[str, str] = {}
    if frame.empty or id_col not in frame.columns:
        return labels, label_to_id
    for _, row in frame.iterrows():
        item_id = str(row.get(id_col) or "").strip()
        if not item_id:
            continue
        name = str(row.get(name_col) or "").strip() if name_col in frame.columns else ""
        label = f"{item_id}{_SEP}{name}" if name else item_id
        labels.append(label)
        label_to_id[label] = item_id
    return labels, label_to_id


def system_acronym_labels(
    systems: pd.DataFrame,
    *,
    include_types: set[str] | None = None,
    exclude_types: set[str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """``UniqueId — Textual Name`` filtered by Type, mapped back to UniqueId."""
    labels: list[str] = []
    label_to_acr: dict[str, str] = {}
    if systems.empty or SYSTEM_UNIQUE_ID not in systems.columns:
        return labels, label_to_acr
    for _, row in systems.iterrows():
        acr = str(row.get(SYSTEM_UNIQUE_ID) or "").strip()
        if not acr:
            continue
        typ = str(row.get("Type") or "").strip()
        if include_types is not None and typ not in include_types:
            continue
        if exclude_types is not None and typ in exclude_types:
            continue
        name = str(row.get(SYSTEM_TEXTUAL_NAME) or "").strip()
        label = f"{acr}{_SEP}{name}" if name else acr
        labels.append(label)
        label_to_acr[label] = acr
    labels.sort()
    return labels, label_to_acr


def rows_by_unique_id(systems: pd.DataFrame) -> dict[str, dict[str, str]]:
    """0_Systems rows as plain string dicts, keyed by UniqueId."""
    out: dict[str, dict[str, str]] = {}
    if systems.empty or SYSTEM_UNIQUE_ID not in systems.columns:
        return out
    for _, row in systems.iterrows():
        uid = str(row.get(SYSTEM_UNIQUE_ID) or "").strip()
        if uid:
            out[uid] = {c: str(row.get(c, "") or "") for c in systems.columns}
    return out


def instance_endpoint_labels(
    systems: pd.DataFrame,
    *,
    exclude_types: set[str] | None = None,
    extra_tokens: list[str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Exhaustive Sender/Receiver endpoints: instance tokens + singletons.

    Unlike the generic ``UniqueId — Name`` filter list, this expands multiplicity
    (``FCC-1``, ``HICU-1``, ``BMU-1-1``, …) and labels each with the textual name.
    """
    exclude_types = exclude_types or {"Aircraft", "Domain", "Zone"}
    labels: list[str] = []
    label_to_val: dict[str, str] = {}
    if systems.empty or SYSTEM_UNIQUE_ID not in systems.columns:
        return labels, label_to_val

    by_acr = rows_by_unique_id(systems)
    tree = SystemTree(list(by_acr.values()))

    def _add(token: str, name: str) -> None:
        token = (token or "").strip()
        if not token:
            return
        label = f"{token}{_SEP}{name}" if name else token
        if label in label_to_val:
            return
        labels.append(label)
        label_to_val[label] = token

    for acr, row in by_acr.items():
        typ = (row.get("Type") or "").strip()
        if typ in exclude_types:
            continue
        name = (row.get(SYSTEM_TEXTUAL_NAME) or "").strip()

        for token in tree.instance_tokens(acr):
            _add(token, name)

    acr_names = {
        a: (by_acr[a].get(SYSTEM_TEXTUAL_NAME) or "").strip() for a in by_acr
    }
    for raw in extra_tokens or []:
        tok = str(raw or "").strip()
        if not tok or tok in label_to_val.values():
            continue
        name = ""
        for acr, nm in sorted(acr_names.items(), key=lambda x: -len(x[0])):
            if tok == acr or tok.startswith(f"{acr}-"):
                name = nm
                break
        _add(tok, name)

    labels.sort()
    return labels, label_to_val


def _label_for_value(label_to_value: dict[str, str], value: str) -> str:
    if not value:
        return ""
    for lab, mapped in label_to_value.items():
        if mapped == value:
            return lab
    return ""


def labeled_select(
    label: str,
    labels: list[str],
    label_to_value: dict[str, str],
    *,
    key: str,
    current: str = "",
    allow_empty: bool = True,
    with_filter: bool = False,
) -> str:
    """Selectbox of labeled options; returns the bare value.

    Widget state lives under ``{key}_label`` so callers can sync display labels
    without colliding with bare-id session keys.
    """
    widget_key = f"{key}_label"
    options = labels
    if with_filter:
        filt = st.text_input(f"Filter {label}", key=f"{key}_filt")
        if filt.strip():
            q = filt.strip().lower()
            options = [x for x in labels if q in x.lower()]
    display = (["", *options]) if allow_empty else (options or [""])

    if widget_key not in st.session_state:
        st.session_state[widget_key] = _label_for_value(label_to_value, current)
    else:
        prev = st.session_state[widget_key]
        if prev and prev not in display:
            st.session_state[widget_key] = _label_for_value(label_to_value, current)
        elif prev and prev not in label_to_value and current:
            # Stale bare value left in session — coerce to label.
            st.session_state[widget_key] = _label_for_value(label_to_value, prev) or (
                _label_for_value(label_to_value, current)
            )

    choice = st.selectbox(label, options=display, key=widget_key)
    return label_to_value.get(choice, "") if choice else ""


def labeled_acronym_select(
    label: str,
    labels: list[str],
    label_to_acr: dict[str, str],
    *,
    key: str,
    current: str = "",
    allow_empty: bool = True,
    with_filter: bool = False,
) -> str:
    """Alias for ``labeled_select`` (systems / LRU acronyms)."""
    return labeled_select(
        label,
        labels,
        label_to_acr,
        key=key,
        current=current,
        allow_empty=allow_empty,
        with_filter=with_filter,
    )


def labeled_multi_select(
    label: str,
    labels: list[str],
    label_to_value: dict[str, str],
    *,
    key: str,
    current: list[str] | None = None,
) -> list[str]:
    """Multiselect of labeled options; returns bare values."""
    value_to_label = {val: lab for lab, val in label_to_value.items()}

    def _normalize(items: list[str]) -> list[str]:
        out: list[str] = []
        for item in items:
            item = str(item).strip()
            if not item:
                continue
            if item in label_to_value:
                out.append(item)
            elif item in value_to_label:
                out.append(value_to_label[item])
        return out

    if key not in st.session_state:
        st.session_state[key] = _normalize(list(current or []))
    else:
        normalized = _normalize(list(st.session_state.get(key) or []))
        if normalized != list(st.session_state.get(key) or []):
            st.session_state[key] = normalized

    chosen = st.multiselect(label, options=labels, key=key)
    return [label_to_value[c] for c in chosen if c in label_to_value]


def labeled_multi_acronym(
    label: str,
    labels: list[str],
    label_to_acr: dict[str, str],
    *,
    key: str,
    current: list[str] | None = None,
) -> list[str]:
    """Alias for ``labeled_multi_select`` (systems / LRU acronyms)."""
    return labeled_multi_select(
        label, labels, label_to_acr, key=key, current=current
    )


def table_select_id(
    view: pd.DataFrame,
    id_col: str,
    *,
    key: str,
) -> str:
    """Show a single-row selectable table; return the selected id or \"\"."""
    if view.empty or id_col not in view.columns:
        st.dataframe(view, width="stretch", hide_index=True, key=f"{key}_empty")
        return ""
    event = st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=key,
    )
    selection = getattr(event, "selection", None)
    rows = list(getattr(selection, "rows", []) or []) if selection is not None else []
    if not rows:
        return ""
    idx = int(rows[0])
    if idx < 0 or idx >= len(view):
        return ""
    return str(view.iloc[idx][id_col] or "").strip()


def _token_matches_acronym(token: str, acronym: str) -> bool:
    """True if ``token`` is the bare acronym or any of its instances (``ACR-…``)."""
    token = (token or "").strip()
    acronym = (acronym or "").strip()
    if not token or not acronym:
        return False
    if token == acronym:
        return True
    return token.startswith(f"{acronym}-")


def filter_buses_by_acronym(
    buses: pd.DataFrame, acronyms: str | list[str]
) -> pd.DataFrame:
    """Rows where Sender or Receiver mentions any instance of the given acronym(s)."""
    if buses.empty:
        return buses.iloc[0:0].copy()
    if isinstance(acronyms, str):
        targets = [acronyms.strip()] if acronyms.strip() else []
    else:
        targets = [a.strip() for a in acronyms if str(a).strip()]
    targets = [a for a in targets if a]
    if not targets:
        return buses.copy()

    endpoint_cols = [c for c in (SENDER, RECEIVER) if c in buses.columns]
    if not endpoint_cols:
        return buses.iloc[0:0].copy()

    def row_matches(row: pd.Series) -> bool:
        blob = ";".join(str(row.get(col) or "") for col in endpoint_cols)
        tokens = [t.strip() for t in blob.split(";") if t.strip()]
        return any(
            _token_matches_acronym(tok, acr) for tok in tokens for acr in targets
        )

    mask = buses.apply(row_matches, axis=1)
    return buses.loc[mask].copy()
