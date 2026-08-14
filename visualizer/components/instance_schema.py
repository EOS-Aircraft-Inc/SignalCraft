"""Containment / instance-count schema for the Edit data UI."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from icd_instances import ROOT_TOKEN, SystemTree

from visualizer.components.selectors import rows_by_unique_id
from visualizer.data.models import (
    INSTALLED_IN,
    SYSTEM_TEXTUAL_NAME,
    SYSTEM_UNIQUE_ID,
)


def containment_schema_lines(
    systems: pd.DataFrame,
    unique_id: str,
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[list[str], int]:
    """Return display lines and aircraft-total for ``unique_id``.

    ``overrides`` patches the edited row (UniqueId, parent, multiplicity, token, type).
    """
    by_id = rows_by_unique_id(systems)
    overrides = dict(overrides or {})
    target = (overrides.get(SYSTEM_UNIQUE_ID) or unique_id or "").strip()
    if not target:
        return [], 0

    # Apply live edits onto a copy of the target row (or create it).
    base = dict(by_id.get(target) or {})
    for key in (
        SYSTEM_UNIQUE_ID,
        SYSTEM_TEXTUAL_NAME,
        "Type",
        INSTALLED_IN,
        "Multiplicity",
    ):
        if key in overrides:
            base[key] = str(overrides[key] or "")
    by_id[target] = base
    tree = SystemTree(list(by_id.values()))

    typ = (base.get("Type") or "").strip()
    if typ == "Domain":
        name = base.get(SYSTEM_TEXTUAL_NAME) or target
        return [
            f"<b>{target}</b> — {name}",
            "<i>Domain: not instantiated (no Multiplicity).</i>",
        ], 0

    chain = list(reversed(tree.chain(target)))  # root → leaf
    if not chain:
        return [f"No containment path for `{target}`."], 0

    lines: list[str] = []
    running = 1
    for depth, uid in enumerate(chain):
        row = by_id.get(uid) or {}
        name = row.get(SYSTEM_TEXTUAL_NAME) or uid
        mult = tree.multiplicity(uid) or (1 if uid == ROOT_TOKEN else 0)
        tokens = tree.tokens(uid)
        if mult >= 1:
            running *= mult if mult else 1
        indent = "&nbsp;&nbsp;" * depth
        branch = "↳ " if depth else ""
        if tokens:
            tok_txt = ", ".join(tokens)
            if len(tokens) > 8:
                tok_txt = ", ".join(tokens[:8]) + f", … (+{len(tokens) - 8})"
            level_txt = f"instances: {tok_txt}"
        elif mult == 1:
            level_txt = "singleton (no token)"
        else:
            level_txt = "no instance token"
        mult_txt = f"×{mult}/parent" if mult else "×?"
        lines.append(
            f"{indent}{branch}<b>{uid}</b> — {name}<br>"
            f"{indent}&nbsp;&nbsp;{mult_txt} · {level_txt} · "
            f"<b>aircraft total so far: {running}</b>"
        )

    lines.append("")
    leaf = chain[-1]
    lines.append(f"<b>Total on aircraft for {leaf}: {running}</b>")
    return lines, running


def render_containment_schema(
    systems: pd.DataFrame,
    unique_id: str,
    *,
    overrides: dict[str, str] | None = None,
) -> None:
    """Streamlit block: AC → component instance schema."""
    st.markdown("##### Containment & instances")
    lines, _total = containment_schema_lines(
        systems, unique_id, overrides=overrides
    )
    if not lines:
        st.caption("Select or enter a UniqueId to preview the instance tree.")
        return
    st.markdown("<br>".join(lines), unsafe_allow_html=True)
