"""Labeled entity pickers for the Edit data UI.

External references display as ``Id — Name`` / ``Acronym — Name`` and widgets
return bare ids/acronyms for persistence. Filter text boxes are opt-in
(``with_filter=True``) — do not add them by default.
"""

from __future__ import annotations

import re
from itertools import product

import pandas as pd
import streamlit as st

_SEP = " — "
_PARENT_COL = "Installed In/Part of"
_COUNTER = re.compile(r"\{(n+)\}")


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
    """``Acronym — System Name`` filtered by Type, mapped back to acronym."""
    labels: list[str] = []
    label_to_acr: dict[str, str] = {}
    if systems.empty or "Acronym" not in systems.columns:
        return labels, label_to_acr
    for _, row in systems.iterrows():
        acr = str(row.get("Acronym") or "").strip()
        if not acr:
            continue
        typ = str(row.get("Type") or "").strip()
        if include_types is not None and typ not in include_types:
            continue
        if exclude_types is not None and typ in exclude_types:
            continue
        name = str(row.get("System Name") or "").strip()
        label = f"{acr}{_SEP}{name}" if name else acr
        labels.append(label)
        label_to_acr[label] = acr
    labels.sort()
    return labels, label_to_acr


def dimension_acronym_labels(
    systems: pd.DataFrame,
) -> tuple[list[str], dict[str, str]]:
    """``Acronym — Name`` for systems with Multiplicity > 1 (instance dimensions)."""
    labels: list[str] = []
    label_to_acr: dict[str, str] = {}
    if systems.empty:
        return labels, label_to_acr
    for _, row in systems.iterrows():
        acr = str(row.get("Acronym") or "").strip()
        mult = str(row.get("Multiplicity") or "").strip()
        if not acr or not mult.isdigit() or int(mult) <= 1:
            continue
        name = str(row.get("System Name") or "").strip()
        label = f"{acr}{_SEP}{name}" if name else acr
        labels.append(label)
        label_to_acr[label] = acr
    labels.sort()
    return labels, label_to_acr


def dimension_acronyms(systems: pd.DataFrame) -> list[str]:
    _, label_to_acr = dimension_acronym_labels(systems)
    return sorted(set(label_to_acr.values()))


def acronym_options(systems: pd.DataFrame) -> list[str]:
    """Bare acronym list (prefer ``system_acronym_labels`` for UI pickers)."""
    if systems.empty or "Acronym" not in systems.columns:
        return []
    return sorted(
        {str(a).strip() for a in systems["Acronym"].dropna() if str(a).strip()}
    )


def _expand_token_pattern(pattern: str, count: int) -> list[str]:
    pattern = (pattern or "").strip()
    if not pattern or count < 1:
        return []
    match = _COUNTER.search(pattern)
    if not match:
        return [p.strip() for p in pattern.split(";") if p.strip()]
    width = len(match.group(1))
    return [
        _COUNTER.sub(f"{index:0{width}d}", pattern) for index in range(1, count + 1)
    ]


def _containment_chain(
    by_acr: dict[str, dict[str, str]], acronym: str
) -> list[str]:
    result: list[str] = []
    node = acronym
    while node and node in by_acr and node not in result:
        result.append(node)
        node = (by_acr[node].get(_PARENT_COL) or "").strip()
    return result


def _multi_ancestor_counts(
    by_acr: dict[str, dict[str, str]], acronym: str
) -> list[int]:
    """Multiplicities of ancestors with Multiplicity > 1, outermost first."""
    chain = list(reversed(_containment_chain(by_acr, acronym)))  # root → leaf
    counts: list[int] = []
    for node in chain:
        if node == acronym:
            break
        mult_s = (by_acr[node].get("Multiplicity") or "").strip()
        mult = int(mult_s) if mult_s.isdigit() else 0
        if mult > 1:
            counts.append(mult)
    return counts


def instance_endpoint_labels(
    systems: pd.DataFrame,
    *,
    exclude_types: set[str] | None = None,
    extra_tokens: list[str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Exhaustive Writer/Receiver endpoints: instance tokens + singletons.

    Unlike the generic ``Acronym — Name`` filter list, this expands multiplicity
    (``FCC-1``, ``HICU-1``, ``BMU-1-1``, …) and labels each with the system name.
    """
    exclude_types = exclude_types or {"Aircraft", "System", "Zone"}
    labels: list[str] = []
    label_to_val: dict[str, str] = {}
    if systems.empty or "Acronym" not in systems.columns:
        return labels, label_to_val

    by_acr: dict[str, dict[str, str]] = {}
    for _, row in systems.iterrows():
        acr = str(row.get("Acronym") or "").strip()
        if acr:
            by_acr[acr] = {c: str(row.get(c, "") or "") for c in systems.columns}

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
        name = (row.get("System Name") or "").strip()
        mult_s = (row.get("Multiplicity") or "").strip()
        mult = int(mult_s) if mult_s.isdigit() else 1
        pattern = (row.get("Instance Token") or "").strip()

        if pattern and mult > 1:
            for tok in _expand_token_pattern(pattern, mult):
                _add(tok, name)
            continue

        ancestor_counts = _multi_ancestor_counts(by_acr, acr)
        if not ancestor_counts:
            _add(acr, name)
            continue
        for idxs in product(*[range(1, n + 1) for n in ancestor_counts]):
            _add(f"{acr}-" + "-".join(str(i) for i in idxs), name)

    acr_names = {
        a: (by_acr[a].get("System Name") or "").strip() for a in by_acr
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
    display = ([""] + options) if allow_empty else (options or [""])

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


def buses_for_lru(buses: pd.DataFrame, lrus: list[str]) -> list[str]:
    """Family handles (Bus Definition) where any LRU appears in Writer/Receiver."""
    if buses.empty or not lrus:
        return []
    matched = filter_buses_by_acronym(buses, lrus)
    if matched.empty:
        return []
    def_col = (
        "Bus Definition"
        if "Bus Definition" in matched.columns
        else "definition_tab"
    )
    if def_col not in matched.columns:
        return []
    return sorted(
        {
            str(v).strip()
            for v in matched[def_col].dropna()
            if str(v).strip()
        }
    )


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
    """Rows where Writer or Receiver mentions any instance of the given acronym(s)."""
    if buses.empty:
        return buses.iloc[0:0].copy()
    if isinstance(acronyms, str):
        targets = [acronyms.strip()] if acronyms.strip() else []
    else:
        targets = [a.strip() for a in acronyms if str(a).strip()]
    targets = [a for a in targets if a]
    if not targets:
        return buses.copy()

    writer_col = "Writer" if "Writer" in buses.columns else "equipment_connected"
    receiver_col = "Receiver" if "Receiver" in buses.columns else "equipment_connected"
    if writer_col not in buses.columns and receiver_col not in buses.columns:
        return buses.iloc[0:0].copy()

    def row_matches(row: pd.Series) -> bool:
        blob = ";".join(
            [
                str(row.get(writer_col) or "") if writer_col in row.index else "",
                str(row.get(receiver_col) or "") if receiver_col in row.index else "",
            ]
        )
        tokens = [t.strip() for t in blob.split(";") if t.strip()]
        return any(
            _token_matches_acronym(tok, acr) for tok in tokens for acr in targets
        )

    mask = buses.apply(row_matches, axis=1)
    return buses.loc[mask].copy()
