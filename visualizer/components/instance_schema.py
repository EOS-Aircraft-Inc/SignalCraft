"""Containment / instance-count schema for the Edit data UI."""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from visualizer.data.models import (
    INSTALLED_IN,
    SYSTEM_TEXTUAL_NAME,
    SYSTEM_UNIQUE_ID,
)

_COUNTER = re.compile(r"\{(n+)\}")
_PARENT_COL = INSTALLED_IN


def _rows_by_unique_id(systems: pd.DataFrame) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if systems.empty or SYSTEM_UNIQUE_ID not in systems.columns:
        return out
    for _, row in systems.iterrows():
        uid = str(row.get(SYSTEM_UNIQUE_ID) or "").strip()
        if uid:
            out[uid] = {c: str(row.get(c, "") or "") for c in systems.columns}
    return out


def _level_tokens(mult: int, token_pattern: str) -> list[str]:
    token_pattern = (token_pattern or "").strip()
    if not token_pattern:
        return []
    match = _COUNTER.search(token_pattern)
    if not match:
        return [p.strip() for p in token_pattern.split(";") if p.strip()]
    if mult < 1:
        return []
    width = len(match.group(1))
    return [
        _COUNTER.sub(f"{index:0{width}d}", token_pattern)
        for index in range(1, mult + 1)
    ]


def _chain(by_id: dict[str, dict[str, str]], unique_id: str) -> list[str]:
    result: list[str] = []
    node = unique_id
    while node and node in by_id and node not in result:
        result.append(node)
        node = (by_id[node].get(_PARENT_COL) or "").strip()
    return result


def containment_schema_lines(
    systems: pd.DataFrame,
    unique_id: str,
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[list[str], int]:
    """Return display lines and aircraft-total for ``unique_id``.

    ``overrides`` patches the edited row (UniqueId, parent, multiplicity, token, type).
    """
    by_id = _rows_by_unique_id(systems)
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
        _PARENT_COL,
        "Multiplicity",
        "Instance Token",
    ):
        if key in overrides:
            base[key] = str(overrides[key] or "")
    by_id[target] = base

    typ = (base.get("Type") or "").strip()
    if typ == "System":
        name = base.get(SYSTEM_TEXTUAL_NAME) or target
        return [
            f"<b>{target}</b> — {name}",
            "<i>Functional system: not instantiated "
            "(no Multiplicity / Instance Token).</i>",
        ], 0

    chain = list(reversed(_chain(by_id, target)))  # root → leaf
    if not chain:
        return [f"No containment path for `{target}`."], 0

    lines: list[str] = []
    running = 1
    for depth, uid in enumerate(chain):
        row = by_id.get(uid) or {}
        name = row.get(SYSTEM_TEXTUAL_NAME) or uid
        mult_s = (row.get("Multiplicity") or "").strip()
        mult = int(mult_s) if mult_s.isdigit() else (1 if uid == "AC" else 0)
        token_pat = row.get("Instance Token") or ""
        tokens = _level_tokens(mult, token_pat)
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
