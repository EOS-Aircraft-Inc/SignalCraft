"""Containment / instance-count schema for the Edit data UI."""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

_COUNTER = re.compile(r"\{(n+)\}")
_PARENT_COL = "Installed In/Part of"


def _rows_by_acronym(systems: pd.DataFrame) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if systems.empty or "Acronym" not in systems.columns:
        return out
    for _, row in systems.iterrows():
        acr = str(row.get("Acronym") or "").strip()
        if acr:
            out[acr] = {c: str(row.get(c, "") or "") for c in systems.columns}
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


def _chain(by_acr: dict[str, dict[str, str]], acronym: str) -> list[str]:
    result: list[str] = []
    node = acronym
    while node and node in by_acr and node not in result:
        result.append(node)
        node = (by_acr[node].get(_PARENT_COL) or "").strip()
    return result


def containment_schema_lines(
    systems: pd.DataFrame,
    acronym: str,
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[list[str], int]:
    """Return display lines and aircraft-total for ``acronym``.

    ``overrides`` patches the edited row (Acronym, parent, multiplicity, token, type).
    """
    by_acr = _rows_by_acronym(systems)
    overrides = dict(overrides or {})
    target = (overrides.get("Acronym") or acronym or "").strip()
    if not target:
        return [], 0

    # Apply live edits onto a copy of the target row (or create it).
    base = dict(by_acr.get(target) or {})
    for key in (
        "Acronym",
        "System Name",
        "Type",
        _PARENT_COL,
        "Multiplicity",
        "Instance Token",
    ):
        if key in overrides:
            base[key] = str(overrides[key] or "")
    by_acr[target] = base

    typ = (base.get("Type") or "").strip()
    if typ == "System":
        name = base.get("System Name") or target
        return [
            f"<b>{target}</b> — {name}",
            "<i>Functional system: not instantiated "
            "(no Multiplicity / Instance Token).</i>",
        ], 0

    chain = list(reversed(_chain(by_acr, target)))  # root → leaf
    if not chain:
        return [f"No containment path for `{target}`."], 0

    lines: list[str] = []
    running = 1
    for depth, acr in enumerate(chain):
        row = by_acr.get(acr) or {}
        name = row.get("System Name") or acr
        mult_s = (row.get("Multiplicity") or "").strip()
        mult = int(mult_s) if mult_s.isdigit() else (1 if acr == "AC" else 0)
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
            f'{indent}{branch}<b>{acr}</b> — {name}<br>'
            f"{indent}&nbsp;&nbsp;{mult_txt} · {level_txt} · "
            f"<b>aircraft total so far: {running}</b>"
        )

    lines.append("")
    leaf = chain[-1]
    lines.append(f"<b>Total on aircraft for {leaf}: {running}</b>")
    return lines, running


def render_containment_schema(
    systems: pd.DataFrame,
    acronym: str,
    *,
    overrides: dict[str, str] | None = None,
) -> None:
    """Streamlit block: AC → component instance schema."""
    st.markdown("##### Containment & instances")
    lines, _total = containment_schema_lines(
        systems, acronym, overrides=overrides
    )
    if not lines:
        st.caption("Select or enter an acronym to preview the instance tree.")
        return
    st.markdown("<br>".join(lines), unsafe_allow_html=True)
