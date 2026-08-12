"""Shared Streamlit filter widgets."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from visualizer.components.selectors import system_acronym_labels


def _as_columns(column: str | list[str], df: pd.DataFrame) -> list[str]:
    cols = [column] if isinstance(column, str) else list(column)
    return [c for c in cols if c in df.columns]


def _present_values(df: pd.DataFrame, cols: list[str]) -> list[str]:
    """Sorted distinct non-empty values held across ``cols``."""
    return sorted(
        {
            str(v).strip()
            for col in cols
            for v in df[col].dropna().unique()
            if str(v).strip()
        }
    )


def system_filter(
    df: pd.DataFrame,
    column: str | list[str] = "System",
    key: str = "sys",
    *,
    systems: pd.DataFrame | None = None,
) -> list[str]:
    """Table filter for one or more system UniqueId columns.

    Pass several columns to offer the union of the systems they mention.
    When ``systems`` is provided, options show ``UniqueId — Name``; returned
    values are always bare UniqueIds for filtering.
    """
    cols = _as_columns(column, df)
    if df.empty or not cols:
        return []
    present = _present_values(df, cols)
    if systems is not None and not systems.empty:
        _, label_to_acr = system_acronym_labels(systems)
        acr_to_label = {acr: lab for lab, acr in label_to_acr.items()}
        options = [acr_to_label.get(a, a) for a in present]
        chosen = st.multiselect("System", options, key=key)
        return [label_to_acr.get(c, c) for c in chosen]
    return st.multiselect("System", present, key=key)


def value_filter(
    df: pd.DataFrame,
    column: str | list[str],
    *,
    label: str,
    key: str,
) -> list[str]:
    """Table filter over the distinct values a plain column holds.

    Same shape as ``system_filter`` but for controlled-vocabulary columns such
    as ``Signal Role``. Options are the values actually present in the sheet, so
    a vocabulary entry nobody has used yet never appears as an empty filter.
    """
    cols = _as_columns(column, df)
    if df.empty or not cols:
        return []
    present = _present_values(df, cols)
    if not present:
        return []
    return st.multiselect(label, present, key=key)


def apply_text_search(df: pd.DataFrame, query: str, columns: list[str]) -> pd.DataFrame:
    if not query or df.empty:
        return df
    q = query.lower()
    mask = pd.Series(False, index=df.index)
    for col in columns:
        if col in df.columns:
            mask |= df[col].fillna("").astype(str).str.lower().str.contains(q, regex=False)
    return df.loc[mask]


def filter_by_values(
    df: pd.DataFrame, values: list[str], column: str | list[str]
) -> pd.DataFrame:
    """Keep rows where *any* of ``column`` matches one of ``values``."""
    cols = _as_columns(column, df)
    if not values or df.empty or not cols:
        return df
    mask = pd.Series(False, index=df.index)
    for col in cols:
        mask |= df[col].isin(values)
    return df.loc[mask]


def filter_by_systems(
    df: pd.DataFrame, systems: list[str], column: str | list[str] = "System"
) -> pd.DataFrame:
    """Keep rows whose system column matches one of ``systems``."""
    return filter_by_values(df, systems, column)
