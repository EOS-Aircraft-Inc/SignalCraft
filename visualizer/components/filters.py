"""Shared Streamlit filter widgets."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from visualizer.components.selectors import system_acronym_labels


def system_filter(
    df: pd.DataFrame,
    column: str = "System",
    key: str = "sys",
    *,
    systems: pd.DataFrame | None = None,
) -> list[str]:
    """Table filter for a System/acronym column.

    When ``systems`` is provided, options show ``Acronym — Name``; returned
    values are always bare acronyms for filtering.
    """
    if df.empty or column not in df.columns:
        return []
    present = sorted(
        {str(v).strip() for v in df[column].dropna().unique() if str(v).strip()}
    )
    if systems is not None and not systems.empty:
        _, label_to_acr = system_acronym_labels(systems)
        acr_to_label = {acr: lab for lab, acr in label_to_acr.items()}
        options = [acr_to_label.get(a, a) for a in present]
        chosen = st.multiselect("System", options, key=key)
        return [label_to_acr.get(c, c) for c in chosen]
    return st.multiselect("System", present, key=key)


def apply_text_search(df: pd.DataFrame, query: str, columns: list[str]) -> pd.DataFrame:
    if not query or df.empty:
        return df
    q = query.lower()
    mask = pd.Series(False, index=df.index)
    for col in columns:
        if col in df.columns:
            mask |= df[col].fillna("").astype(str).str.lower().str.contains(q, regex=False)
    return df.loc[mask]


def filter_by_systems(
    df: pd.DataFrame, systems: list[str], column: str = "System"
) -> pd.DataFrame:
    if not systems or df.empty or column not in df.columns:
        return df
    return df[df[column].isin(systems)]
