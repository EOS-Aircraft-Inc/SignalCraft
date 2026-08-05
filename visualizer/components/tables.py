"""Table helpers for Streamlit."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def show_dataframe(df: pd.DataFrame, *, height: int = 360) -> None:
    if df is None or df.empty:
        st.info("No rows to display.")
        return
    st.dataframe(df, width="stretch", height=height)
