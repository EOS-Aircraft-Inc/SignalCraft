"""Table helpers for Streamlit."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder


def show_dataframe(df: pd.DataFrame, *, height: int = 360) -> None:
    if df is None or df.empty:
        st.info("No rows to display.")
        return
    st.dataframe(df, width="stretch", height=height)


def show_aggrid(
    df: pd.DataFrame,
    *,
    key: str,
    height: int = 360,
    selection_column: str | None = None,
) -> str:
    """AG Grid table with a filter box under every column header.

    Returns the ``selection_column`` value of the clicked row, else "".
    """
    if df is None or df.empty:
        st.info("No rows to display.")
        return ""

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(sortable=True, filter=True, floatingFilter=True, resizable=True)
    gb.configure_selection("single")
    # Size columns to content, then stretch them to fill the container width.
    gb.configure_grid_options(autoSizeStrategy={"type": "fitGridWidth"})
    grid = AgGrid(df, gridOptions=gb.build(), height=height, theme="dark", key=key)

    rows = grid.selected_rows
    if selection_column and rows is not None and not rows.empty:
        return str(rows.iloc[0][selection_column])
    return ""
