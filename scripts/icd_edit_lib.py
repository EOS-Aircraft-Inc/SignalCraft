"""SignalCraft edit engine: blind upsert/delete/rewrite with preflight.

Document shape::

    {
      "rewrite": {"acronyms": [{"from": "A", "to": "B"}], "ids": [{"from": "X", "to": "Y"}]},
      "upsert": {"1_Signals": [{"Signal Id": "SIG-001", "Signal Name": "..."}]},
      "delete": {"ICM_FCS": ["DBUS-099"]},
      "options": {"with_buses": true}
    }

Omitted fields are left unchanged. Explicit "" clears a field.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from icd_csv import (
    collect_ids,
    ensure_sheet,
    join_refs,
    load_manifest,
    next_id,
    read_sheet,
    save_manifest,
    sheet_index,
    split_refs,
    write_sheet,
)
from icd_instances import family_map
from icd_paths import DEFAULT_CSV_DIR
from icd_sheets import (
    CONTROLLED_SHEETS,
    DATABUSES_SHEET,
    README_SHEET,
    SIGNALS_SHEET,
    SYSTEMS_SHEET,
)

CONTROLLED = set(CONTROLLED_SHEETS)

PRIMARY_KEY: dict[str, str] = {
    SYSTEMS_SHEET: "System Id",
    SIGNALS_SHEET: "Signal Id",
    DATABUSES_SHEET: "Bus Id",
}

ID_PREFIX: dict[str, str] = {
    SYSTEMS_SHEET: "SYS",
    SIGNALS_SHEET: "SIG",
    DATABUSES_SHEET: "DBUS",
}

# Semicolon-separated fields that may hold system acronyms / scope dims.
ACRONYM_FIELDS: dict[str, list[str]] = {
    SYSTEMS_SHEET: ["Acronym", "Installed In/Part of", "Functional system"],
    SIGNALS_SHEET: ["Physical System", "Signal Owner", "Repeated Per"],
    DATABUSES_SHEET: ["Writer", "Receiver", "master_lru", "equipment_connected"],
}

PAYLOAD_ACRONYM_FIELDS = ["writer_lru", "receiver_lrus"]

# Columns that may hold cross-sheet identity references.
ID_REF_FIELDS: dict[str, list[str]] = {
    SIGNALS_SHEET: ["Related to"],
    DATABUSES_SHEET: ["Bus Definition", "definition_tab"],
}

PAYLOAD_ID_FIELDS = [
    "signal_id",
]

PAYLOAD_DEFAULT_FIELDS = [
    "Allocation Id",
    "data_name",
    "writer_lru",
    "receiver_lrus",
    "instance_dimension",
    "signal_id",
    "message_or_label",
    "bit_or_field",
    "encoding",
    "unit",
    "scale",
    "resolution",
    "minimum",
    "maximum",
    "update_period_ms",
    "validity",
    "notes",
    "On aircraft ?",
    "On FND ?",
    "On Sim ?",
]


def resolve_signals_sheet_name(manifest: dict | None = None, csv_dir: Path | None = None) -> str:
    """Return the signals catalog sheet present in the workbook."""
    if manifest is None:
        manifest = load_manifest(csv_dir or DEFAULT_CSV_DIR)
    index = sheet_index(manifest)
    if SIGNALS_SHEET in index:
        return SIGNALS_SHEET
    raise KeyError(f"{SIGNALS_SHEET} not found in workbook manifest")

_TOKEN_COUNTER = re.compile(r"^(.*?)(\d+)$")


@dataclass
class CellChange:
    sheet: str
    row_key: str
    column: str
    old: str
    new: str
    action: str = "set"  # set | insert | delete_row


@dataclass
class EditResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    plan: list[CellChange] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)


def _replace_token_in_refs(value: str, old: str, new: str) -> str:
    parts = split_refs(value)
    changed = False
    out: list[str] = []
    for part in parts:
        if part == old:
            out.append(new)
            changed = True
        else:
            out.append(part)
    return join_refs(out) if changed or out != parts else value


def _replace_id_in_value(value: str, old: str, new: str) -> str:
    if not value or old not in value:
        return value
    # Exact ref tokens in semicolon lists, or whole-cell equality.
    if ";" in value or value == old:
        return _replace_token_in_refs(value, old, new)
    if value == old:
        return new
    return value


class IcdEditor:
    def __init__(self, csv_dir: Path | None = None) -> None:
        self.csv_dir = Path(csv_dir) if csv_dir else DEFAULT_CSV_DIR
        self.manifest = load_manifest(self.csv_dir)
        self.sheets: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
        for entry in self.manifest["sheets"]:
            name = str(entry["sheet_name"])
            if name == README_SHEET:
                continue
            try:
                fields, rows = read_sheet(name, self.csv_dir, self.manifest)
            except KeyError:
                continue
            self.sheets[name] = (fields, [dict(r) for r in rows])

    def _fields_rows(self, sheet: str) -> tuple[list[str], list[dict[str, str]]]:
        if sheet not in self.sheets:
            raise KeyError(f"Unknown sheet: {sheet}")
        return self.sheets[sheet]

    def _primary_key(self, sheet: str) -> str:
        if sheet in PRIMARY_KEY:
            return PRIMARY_KEY[sheet]
        fields, _ = self._fields_rows(sheet)
        if "Allocation Id" in fields:
            return "Allocation Id"
        if "Data Id" in fields:
            return "Data Id"
        if "data_id" in fields:
            return "data_id"
        raise KeyError(f"No primary key for sheet {sheet}")

    def _row_index(self, sheet: str) -> dict[str, dict[str, str]]:
        key = self._primary_key(sheet)
        _, rows = self._fields_rows(sheet)
        return {str(r.get(key, "")).strip(): r for r in rows if str(r.get(key, "")).strip()}

    def _all_ids(self, sheet: str) -> list[str]:
        key = self._primary_key(sheet)
        _, rows = self._fields_rows(sheet)
        return collect_ids(rows, key)

    def _is_payload_sheet(self, sheet: str) -> bool:
        return sheet not in CONTROLLED and sheet in self.sheets

    def _ensure_payload_sheet(self, sheet: str) -> None:
        if sheet in self.sheets:
            return
        self.manifest = ensure_sheet(
            sheet, PAYLOAD_DEFAULT_FIELDS, self.csv_dir, self.manifest
        )
        self.sheets[sheet] = (list(PAYLOAD_DEFAULT_FIELDS), [])

    def expand_rewrites(self, document: dict[str, Any]) -> list[CellChange]:
        changes: list[CellChange] = []
        rewrite = document.get("rewrite") or {}
        for item in rewrite.get("acronyms") or []:
            old = str(item.get("from") or "").strip()
            new = str(item.get("to") or "").strip()
            if not old:
                continue
            changes.extend(self._rewrite_acronym(old, new))
        for item in rewrite.get("ids") or []:
            old = str(item.get("from") or "").strip()
            new = str(item.get("to") or "").strip()
            if not old:
                continue
            changes.extend(self._rewrite_id(old, new))
        return changes

    def _rewrite_acronym(self, old: str, new: str) -> list[CellChange]:
        changes: list[CellChange] = []
        for sheet, columns in ACRONYM_FIELDS.items():
            if sheet not in self.sheets:
                continue
            key = self._primary_key(sheet)
            _, rows = self._fields_rows(sheet)
            for row in rows:
                row_id = str(row.get(key, "")).strip() or "?"
                for col in columns:
                    if col not in row:
                        continue
                    before = row.get(col, "")
                    after = _replace_token_in_refs(before, old, new)
                    if after != before:
                        changes.append(
                            CellChange(sheet, row_id, col, before, after)
                        )
        for sheet in list(self.sheets):
            if not self._is_payload_sheet(sheet):
                continue
            key = self._primary_key(sheet)
            _, rows = self._fields_rows(sheet)
            for row in rows:
                row_id = str(row.get(key, "")).strip() or "?"
                for col in PAYLOAD_ACRONYM_FIELDS:
                    if col not in row:
                        continue
                    before = row.get(col, "")
                    after = _replace_token_in_refs(before, old, new)
                    if after != before:
                        changes.append(
                            CellChange(sheet, row_id, col, before, after)
                        )
        return changes

    def _rewrite_id(self, old: str, new: str) -> list[CellChange]:
        changes: list[CellChange] = []
        for sheet, (fields, rows) in self.sheets.items():
            try:
                key = self._primary_key(sheet)
            except KeyError:
                continue
            extra_cols = list(ID_REF_FIELDS.get(sheet, []))
            if self._is_payload_sheet(sheet):
                extra_cols = list(PAYLOAD_ID_FIELDS)
            scan_cols = {key, *extra_cols, *fields}
            for row in rows:
                row_id = str(row.get(key, "")).strip() or "?"
                for col in scan_cols:
                    if col not in row:
                        continue
                    before = row.get(col, "")
                    after = _replace_id_in_value(before, old, new)
                    if after != before:
                        changes.append(
                            CellChange(sheet, row_id, col, before, after)
                        )
        return changes

    def plan_upserts(self, document: dict[str, Any]) -> list[CellChange]:
        changes: list[CellChange] = []
        upsert = document.get("upsert") or {}
        for sheet, items in upsert.items():
            if not items:
                continue
            if sheet not in self.sheets and sheet not in CONTROLLED:
                self._ensure_payload_sheet(sheet)
            if sheet not in self.sheets:
                raise KeyError(f"Unknown sheet for upsert: {sheet}")
            fields, rows = self._fields_rows(sheet)
            key = self._primary_key(sheet)
            index = {
                str(r.get(key, "")).strip(): r
                for r in rows
                if str(r.get(key, "")).strip()
            }
            existing_ids = list(index.keys())
            for raw in items:
                item = {str(k): v for k, v in dict(raw).items()}
                # Normalize lists to semicolon refs for known multi fields.
                for fk, fv in list(item.items()):
                    if isinstance(fv, list):
                        item[fk] = join_refs([str(x).strip() for x in fv])
                    elif fv is None:
                        item[fk] = ""
                    else:
                        item[fk] = str(fv)

                row_id = str(item.get(key, "")).strip()
                if not row_id:
                    prefix = ID_PREFIX.get(sheet, "ID")
                    if sheet not in ID_PREFIX and key in {
                        "Allocation Id",
                        "Data Id",
                    }:
                        prefix = "DBUS"
                    row_id = next_id(existing_ids + collect_ids(rows, key), prefix)
                    item[key] = row_id
                    existing_ids.append(row_id)

                if row_id in index:
                    row = index[row_id]
                    for col, new_val in item.items():
                        if col not in fields:
                            continue
                        old_val = row.get(col, "")
                        if new_val != old_val:
                            changes.append(
                                CellChange(sheet, row_id, col, old_val, new_val)
                            )
                else:
                    blank = {f: "" for f in fields}
                    blank.update({k: v for k, v in item.items() if k in fields})
                    blank[key] = row_id
                    for col in fields:
                        changes.append(
                            CellChange(
                                sheet,
                                row_id,
                                col,
                                "",
                                blank.get(col, ""),
                                action="insert",
                            )
                        )
                    # Track allocated ids without mutating sheet state.
                    index[row_id] = blank
                    existing_ids.append(row_id)
        return changes

    def plan_deletes(self, document: dict[str, Any]) -> list[CellChange]:
        changes: list[CellChange] = []
        delete = document.get("delete") or {}
        for sheet, ids in delete.items():
            if sheet not in self.sheets:
                continue
            key = self._primary_key(sheet)
            index = self._row_index(sheet)
            for raw_id in ids or []:
                row_id = str(raw_id).strip()
                if not row_id:
                    continue
                row = index.get(row_id)
                if row is None:
                    changes.append(
                        CellChange(
                            sheet, row_id, key, "", "", action="delete_row"
                        )
                    )
                    continue
                changes.append(
                    CellChange(
                        sheet,
                        row_id,
                        key,
                        row_id,
                        "",
                        action="delete_row",
                    )
                )
        return changes

    def detect_bus_multiplicity_impact(
        self, document: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Return families impacted by 0_Systems multiplicity changes."""
        impacts: list[dict[str, Any]] = []
        upserts = (document.get("upsert") or {}).get(SYSTEMS_SHEET) or []
        if not upserts or SYSTEMS_SHEET not in self.sheets:
            return impacts
        systems = self._row_index(SYSTEMS_SHEET)
        buses = self.sheets[DATABUSES_SHEET][1] if DATABUSES_SHEET in self.sheets else []
        families = family_map(buses)

        for item in upserts:
            sid = str(item.get("System Id") or "").strip()
            row = systems.get(sid)
            if row is None and "Acronym" in item:
                # match by acronym
                acr = str(item.get("Acronym") or "").strip()
                row = next(
                    (r for r in systems.values() if r.get("Acronym", "").strip() == acr),
                    None,
                )
            if row is None:
                continue
            if "Multiplicity" not in item and "Instance Token" not in item:
                continue
            acronym = str(item.get("Acronym") or row.get("Acronym") or "").strip()
            old_mult = (row.get("Multiplicity") or "").strip()
            new_mult = str(item.get("Multiplicity", old_mult)).strip()
            if not new_mult or new_mult == old_mult:
                continue
            if not old_mult.isdigit() or not new_mult.isdigit():
                continue
            old_n, new_n = int(old_mult), int(new_mult)
            token = str(
                item.get("Instance Token") or row.get("Instance Token") or ""
            ).strip()
            for family, members in families.items():
                if len(members) != old_n:
                    continue
                # Prefer families whose bus ids end with _1.._N matching token style.
                if token and "{n" in token:
                    stem = token.split("{")[0].rstrip("-_")
                    if stem and not all(
                        any(stem in m for stem in [stem]) for m in members
                    ):
                        # loose: member contains acronym or family relates
                        pass
                if acronym and not any(
                    acronym in m or acronym.lower() in family.lower() for m in members
                ):
                    # still allow if family name contains acronym
                    if acronym not in family:
                        continue
                impacts.append(
                    {
                        "acronym": acronym,
                        "family": family,
                        "old_multiplicity": old_n,
                        "new_multiplicity": new_n,
                        "members": sorted(members),
                        "token": token,
                    }
                )
        return impacts

    def plan_with_buses(
        self, impacts: list[dict[str, Any]], with_buses: bool
    ) -> list[CellChange]:
        if not with_buses:
            return []
        changes: list[CellChange] = []
        if DATABUSES_SHEET not in self.sheets:
            return changes
        fields, rows = self._fields_rows(DATABUSES_SHEET)
        index = {str(r.get("Bus Id", "")).strip(): r for r in rows}

        for impact in impacts:
            members = list(impact["members"])
            old_n = int(impact["old_multiplicity"])
            new_n = int(impact["new_multiplicity"])
            family = impact["family"]

            def sort_key(bus_id: str) -> int:
                m = _TOKEN_COUNTER.match(bus_id)
                return int(m.group(2)) if m else 0

            members_sorted = sorted(members, key=sort_key)
            if new_n > old_n:
                template_id = members_sorted[-1] if members_sorted else ""
                template = index.get(template_id)
                if not template:
                    continue
                m = _TOKEN_COUNTER.match(template_id)
                if not m:
                    continue
                stem, _ = m.group(1), m.group(2)
                for i in range(old_n + 1, new_n + 1):
                    new_id = f"{stem}{i}"
                    if new_id in index:
                        continue
                    for col in fields:
                        old_val = template.get(col, "")
                        new_val = old_val
                        if col == "Bus Id":
                            new_val = new_id
                        elif col == "name" and old_val:
                            # replace trailing number in name if present
                            new_val = re.sub(r"\d+$", str(i), old_val) if re.search(r"\d+$", old_val) else f"{old_val} {i}"
                        elif col in ("Writer", "Receiver"):
                            new_val = _renumber_instance_refs(old_val, old_n, i)
                        changes.append(
                            CellChange(
                                DATABUSES_SHEET,
                                new_id,
                                col,
                                "",
                                new_val if col != "Bus Definition" else family,
                                action="insert",
                            )
                        )
            elif new_n < old_n:
                for bus_id in members_sorted:
                    m = _TOKEN_COUNTER.match(bus_id)
                    if not m:
                        continue
                    if int(m.group(2)) > new_n:
                        changes.append(
                            CellChange(
                                DATABUSES_SHEET,
                                bus_id,
                                "Bus Id",
                                bus_id,
                                "",
                                action="delete_row",
                            )
                        )
        return changes

    def preflight(
        self,
        document: dict[str, Any],
        plan: list[CellChange],
        impacts: list[dict[str, Any]],
    ) -> list[str]:
        errors: list[str] = []
        options = document.get("options") or {}
        with_buses = options.get("with_buses", None)

        if impacts and with_buses is None:
            families = ", ".join(
                f"{i['family']} ({i['old_multiplicity']}->{i['new_multiplicity']})"
                for i in impacts
            )
            errors.append(
                "Multiplicity change impacts bus families: "
                f"{families}. Set options.with_buses to true (duplicate/remove bus "
                "rows) or false (systems only)."
            )

        # Simulate post-state id sets from plan (lightweight).
        simulated = self._simulate(plan)

        # Delete targets must exist (unless already flagged).
        for change in plan:
            if change.action == "delete_row" and change.old == "" and change.new == "":
                # placeholder for missing — from plan_deletes when missing
                errors.append(
                    f"{change.sheet}: cannot delete unknown id '{change.row_key}'"
                )

        for change in plan:
            if change.action == "delete_row":
                continue
            if change.action == "insert" and change.column == self._primary_key_safe(
                change.sheet
            ):
                # new id collision check against original + other inserts
                pass

        # ID uniqueness for inserts/renames
        for sheet, id_map in simulated["ids"].items():
            seen: dict[str, int] = {}
            for rid in id_map:
                seen[rid] = seen.get(rid, 0) + 1
            for rid, count in seen.items():
                if count > 1:
                    errors.append(f"{sheet}: duplicate id after edit: {rid}")

        # Reference checks on upsert payloads in the document (provided fields).
        systems = set(simulated.get("acronyms") or [])
        signals_sheet = resolve_signals_sheet_name(self.manifest, self.csv_dir)
        signal_ids = set(simulated["ids"].get(signals_sheet, {}).keys())
        bus_ids = set(simulated["ids"].get(DATABUSES_SHEET, {}).keys())
        families = set(family_map(list(simulated["ids"].get(DATABUSES_SHEET, {}).values())).keys())
        # Rebuild bus rows after plan mutations so new Bus Definition values count
        # as known families (creating a bus can introduce a new family name).
        bus_rows = []
        if DATABUSES_SHEET in self.sheets:
            bus_rows = [dict(r) for r in self.sheets[DATABUSES_SHEET][1]]
            pending_inserts: dict[str, dict[str, str]] = {}
            for ch in plan:
                if ch.sheet != DATABUSES_SHEET:
                    continue
                if ch.action == "delete_row":
                    bus_rows = [r for r in bus_rows if r.get("Bus Id") != ch.row_key]
                    pending_inserts.pop(ch.row_key, None)
                elif ch.action == "insert":
                    row = pending_inserts.setdefault(
                        ch.row_key, {"Bus Id": ch.row_key}
                    )
                    row[ch.column] = ch.new
                elif ch.action == "set":
                    applied = False
                    for r in bus_rows:
                        if r.get("Bus Id") == ch.row_key:
                            r[ch.column] = ch.new
                            applied = True
                            break
                    if not applied and ch.row_key in pending_inserts:
                        pending_inserts[ch.row_key][ch.column] = ch.new
            bus_rows.extend(pending_inserts.values())
            families = set(family_map(bus_rows).keys())
            bus_ids = {
                str(r.get("Bus Id") or "").strip()
                for r in bus_rows
                if str(r.get("Bus Id") or "").strip()
            }

        bus_refs = bus_ids | families

        upsert = document.get("upsert") or {}
        for sheet, items in upsert.items():
            for raw in items or []:
                item = dict(raw)
                if sheet == SYSTEMS_SHEET:
                    sid = str(item.get("System Id") or "").strip()
                    existing = (
                        self._row_index(SYSTEMS_SHEET).get(sid, {})
                        if SYSTEMS_SHEET in self.sheets
                        else {}
                    )
                    typ = str(
                        item.get("Type") if "Type" in item else existing.get("Type", "")
                    ).strip()
                    if "Multiplicity" in item or typ:
                        mult = str(
                            item.get("Multiplicity")
                            if "Multiplicity" in item
                            else existing.get("Multiplicity", "")
                        ).strip()
                        if typ in {"Aircraft", "System"} and mult and mult != "1":
                            errors.append(
                                f"0_Systems {sid or '?'}: Type '{typ}' requires "
                                "empty Multiplicity (or '1')"
                            )
                        elif typ in {"Zone", "Component", "Controller"}:
                            if "Multiplicity" in item and (
                                not mult.isdigit() or int(mult) < 1
                            ):
                                errors.append(
                                    f"0_Systems {sid or '?'}: Type '{typ}' requires "
                                    f"Multiplicity as a positive integer (got {mult!r})"
                                )
                            elif mult.isdigit() and int(mult) > 1:
                                token = str(
                                    item.get("Instance Token")
                                    if "Instance Token" in item
                                    else existing.get("Instance Token", "")
                                ).strip()
                                if not token:
                                    errors.append(
                                        f"0_Systems {sid or '?'}: Type '{typ}' with "
                                        f"Multiplicity {mult} requires a non-empty "
                                        "Instance Token"
                                    )
                if sheet == SIGNALS_SHEET:
                    for col in ("Physical System", "Signal Owner", "Repeated Per"):
                        if col not in item:
                            continue
                        for ref in split_refs(str(item.get(col) or "")):
                            if ref and ref not in systems and ref not in {"TBD", "N/A"}:
                                if systems:
                                    errors.append(
                                        f"{sheet}: unknown system acronym '{ref}' in {col}"
                                    )
                    for ref in split_refs(str(item.get("Related to") or "")):
                        if not ref:
                            continue
                        if ref not in signal_ids:
                            errors.append(
                                f"{sheet}: Related to '{ref}' is not a known Signal Id"
                            )
                for col in ("Bus Definition", "definition_tab"):
                    if col not in item:
                        continue
                    # On 10_Databuses, Bus Definition / definition_tab *defines*
                    # the family — it need not already exist.
                    if sheet == DATABUSES_SHEET and col in {
                        "Bus Definition",
                        "definition_tab",
                    }:
                        continue
                    for ref in split_refs(str(item.get(col) or "")):
                        if ref and ref not in bus_refs and ref not in {"TBD", "N/A"}:
                            errors.append(
                                f"{sheet}: {col} '{ref}' is not a known bus or family"
                            )
                for col in (
                    "Physical System",
                    "Signal Owner",
                    "Repeated Per",
                    "writer_lru",
                    "Installed In/Part of",
                    "Writer",
                    "Receiver",
                ):
                    if col not in item:
                        continue
                    for ref in split_refs(str(item.get(col) or "")):
                        if not ref or ref in {"TBD", "N/A"}:
                            continue
                        base = ref.split("-")[0] if "-" in ref else ref
                        if ref in systems or base in systems:
                            continue
                        if systems:
                            errors.append(
                                f"{sheet}: unknown system acronym '{ref}' in {col}"
                            )
                if sheet not in CONTROLLED or self._is_payload_sheet(sheet):
                    if "signal_id" in item:
                        sid = str(item.get("signal_id") or "").strip()
                        if sid and sid not in signal_ids:
                            errors.append(
                                f"{sheet}: signal_id '{sid}' is not a known Signal Id"
                            )
                        if ";" in sid:
                            errors.append(
                                f"{sheet}: signal_id must reference exactly one Signal Id"
                            )

        # New primary keys must not collide with existing unless rewrite owns them.
        rewrite_ids = {
            str(i.get("from") or "").strip(): str(i.get("to") or "").strip()
            for i in (document.get("rewrite") or {}).get("ids") or []
        }
        for ch in plan:
            if ch.action != "insert":
                continue
            pk = self._primary_key_safe(ch.sheet)
            if ch.column != pk:
                continue
            original = set(self._all_ids(ch.sheet)) if ch.sheet in self.sheets else set()
            if ch.new in original and rewrite_ids.get(ch.new) is None:
                # insert of brand-new id that somehow exists
                if ch.old == "" and ch.new in original:
                    # Could be re-plan artifact; only error if not updating
                    existing_upsert = False
                    for raw in (upsert.get(ch.sheet) or []):
                        if str(raw.get(pk) or "").strip() == ch.new:
                            existing_upsert = True
                    if not existing_upsert:
                        errors.append(f"{ch.sheet}: id already used: {ch.new}")

        return errors

    def _primary_key_safe(self, sheet: str) -> str:
        try:
            return self._primary_key(sheet)
        except KeyError:
            return "Allocation Id"

    def _simulate(self, plan: list[CellChange]) -> dict[str, Any]:
        ids: dict[str, dict[str, dict[str, str]]] = {}
        for sheet, (_, rows) in self.sheets.items():
            try:
                key = self._primary_key(sheet)
            except KeyError:
                continue
            ids[sheet] = {
                str(r.get(key, "")).strip(): dict(r)
                for r in rows
                if str(r.get(key, "")).strip()
            }

        for ch in plan:
            if ch.sheet not in ids:
                ids[ch.sheet] = {}
            if ch.action == "delete_row":
                ids[ch.sheet].pop(ch.row_key, None)
                continue
            row = ids[ch.sheet].setdefault(ch.row_key, {})
            row[ch.column] = ch.new
            pk = self._primary_key_safe(ch.sheet)
            if ch.column == pk and ch.old and ch.old != ch.new and ch.old in ids[ch.sheet]:
                # id rename inside row map
                if ch.old != ch.row_key:
                    pass
                moved = ids[ch.sheet].pop(ch.old, row)
                moved[pk] = ch.new
                ids[ch.sheet][ch.new] = moved

        acronyms: set[str] = set()
        for row in ids.get(SYSTEMS_SHEET, {}).values():
            acr = (row.get("Acronym") or "").strip()
            if acr:
                acronyms.add(acr)
        return {"ids": ids, "acronyms": acronyms}

    def apply_plan(self, plan: list[CellChange]) -> list[str]:
        summary: list[str] = []
        # Group by sheet
        by_sheet: dict[str, list[CellChange]] = {}
        for ch in plan:
            by_sheet.setdefault(ch.sheet, []).append(ch)

        for sheet, changes in by_sheet.items():
            if sheet not in self.sheets and any(c.action == "insert" for c in changes):
                self._ensure_payload_sheet(sheet)
            fields, rows = self._fields_rows(sheet)
            key = self._primary_key(sheet)
            index = {
                str(r.get(key, "")).strip(): r
                for r in rows
                if str(r.get(key, "")).strip()
            }

            delete_ids = {c.row_key for c in changes if c.action == "delete_row"}
            if delete_ids:
                rows[:] = [
                    r for r in rows if str(r.get(key, "")).strip() not in delete_ids
                ]
                for did in sorted(delete_ids):
                    summary.append(f"Delete {sheet} {did}")
                index = {
                    str(r.get(key, "")).strip(): r
                    for r in rows
                    if str(r.get(key, "")).strip()
                }

            inserts: dict[str, dict[str, str]] = {}
            for ch in changes:
                if ch.action == "delete_row":
                    continue
                if ch.action == "insert":
                    row = inserts.setdefault(ch.row_key, {f: "" for f in fields})
                    if ch.column in fields:
                        row[ch.column] = ch.new
                    continue
                row = index.get(ch.row_key)
                if row is None:
                    row = inserts.setdefault(ch.row_key, {f: "" for f in fields})
                    if ch.column in fields:
                        row[ch.column] = ch.new
                    continue
                if ch.column in fields:
                    row[ch.column] = ch.new
                if ch.column == key and ch.old and ch.new and ch.old != ch.new:
                    summary.append(f"Rename {sheet} {ch.old} -> {ch.new}")
                else:
                    summary.append(
                        f"Set {sheet} {ch.row_key}.{ch.column}: "
                        f"{ch.old!r} -> {ch.new!r}"
                    )

            for row_id, row in inserts.items():
                row[key] = row_id
                rows.append(row)
                summary.append(f"Insert {sheet} {row_id}")

            # Handle primary key renames in-place already done via column set.
            write_sheet(sheet, fields, rows, self.csv_dir, self.manifest)
            self.sheets[sheet] = (fields, rows)

        # Refresh manifest max_row lightly
        for entry in self.manifest["sheets"]:
            name = str(entry["sheet_name"])
            if name in self.sheets:
                _, rows = self.sheets[name]
                entry["max_row"] = len(rows) + 1
        save_manifest(self.manifest, self.csv_dir)
        return summary


def run_edit(
    document: dict[str, Any],
    csv_dir: Path | None = None,
    dry_run: bool = False,
) -> EditResult:
    editor = IcdEditor(csv_dir)
    try:
        rewrite_plan = editor.expand_rewrites(document)
        # Apply rewrite mentally first so upserts see new ids — actually we
        # collect all plans then apply in order: rewrite sets, then upserts, then deletes.
        upsert_plan = editor.plan_upserts(document)
        delete_plan = editor.plan_deletes(document)
        impacts = editor.detect_bus_multiplicity_impact(document)
        options = document.get("options") or {}
        with_buses = options.get("with_buses", None)
        bus_plan: list[CellChange] = []
        if impacts and with_buses is True:
            bus_plan = editor.plan_with_buses(impacts, True)

        plan = rewrite_plan + upsert_plan + bus_plan + delete_plan
        errors = editor.preflight(document, plan, impacts)
        if errors:
            return EditResult(ok=False, errors=errors, plan=plan)

        if dry_run:
            summary = [
                f"{c.action} {c.sheet} {c.row_key}.{c.column}: {c.old!r} -> {c.new!r}"
                for c in plan
            ]
            warnings = []
            if impacts and with_buses is False:
                warnings.append(
                    "with_buses=false: multiplicity updated without changing "
                    + ", ".join(i["family"] for i in impacts)
                )
            return EditResult(ok=True, plan=plan, summary=summary, warnings=warnings)

        # Apply on a fresh editor state — rewrite/upsert already planned against
        # original; apply sequentially.
        summary = editor.apply_plan(plan)
        return EditResult(ok=True, plan=plan, summary=summary)
    except Exception as exc:  # noqa: BLE001 — surface as edit error
        return EditResult(ok=False, errors=[str(exc)])


def load_document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_result(result: EditResult) -> str:
    lines: list[str] = []
    if result.errors:
        lines.append(f"FAILED ({len(result.errors)} error(s)):")
        for err in result.errors:
            lines.append(f"  - {err}")
    if result.warnings:
        lines.append("Warnings:")
        for w in result.warnings:
            lines.append(f"  ! {w}")
    if result.ok:
        lines.append(f"OK - {len(result.plan)} change(s)")
        for line in result.summary[:200]:
            lines.append(f"  {line}")
        if len(result.summary) > 200:
            lines.append(f"  … {len(result.summary) - 200} more")
    return "\n".join(lines)


def _renumber_instance_refs(value: str, old_index: int, new_index: int) -> str:
    """Best-effort: replace trailing -N tokens equal to template index with new_index."""
    parts = split_refs(value)
    out: list[str] = []
    for part in parts:
        m = _TOKEN_COUNTER.match(part)
        if m and int(m.group(2)) == old_index:
            out.append(f"{m.group(1)}{new_index}")
        else:
            out.append(part)
    return join_refs(out)
