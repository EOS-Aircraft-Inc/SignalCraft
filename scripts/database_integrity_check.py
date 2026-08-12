"""SignalCraft integrity check for Systems + Signals + Databuses CSV export."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from icd_csv import collect_ids, load_manifest, read_sheet, sheet_index, split_refs
from icd_instances import SystemTree, family_map
from icd_paths import DEFAULT_CSV_DIR
from icd_sheets import (
    ALLOCATION_ID,
    BUS_DEFINITION,
    BUS_ID,
    BUS_TOPOLOGIES,
    CONTROLLED_SHEETS,
    DATA_ID,
    DATABUSES_SHEET,
    INSTALLED_IN,
    INTERFACE_TYPE,
    INTERFACE_TYPES,
    INTERFACING_EQUIPMENT,
    RECEIVER,
    RECEIVER_LRUS,
    RELATED_TO,
    REPEATED_PER,
    SIGNAL_ID,
    SIGNAL_ID_REF,
    SIGNAL_OWNER,
    SIGNALS_SHEET,
    SYSTEM_TEXTUAL_NAME,
    SYSTEM_UNIQUE_ID,
    SYSTEMS_SHEET,
    TOPOLOGY,
    WRITER,
    WRITER_LRU,
    formal_topology_label,
    normalize_bus_topology,
)

PLACEHOLDERS = {"", "TBD", "N/A", "TBD / N/A"}


def resolve_signals_sheet(manifest: dict) -> str:
    index = sheet_index(manifest)
    if SIGNALS_SHEET in index:
        return SIGNALS_SHEET
    raise KeyError(f"{SIGNALS_SHEET} not found in workbook manifest")


def controlled_sheets(manifest: dict) -> set[str]:
    return set(CONTROLLED_SHEETS) | {resolve_signals_sheet(manifest)}


def payload_sheets(csv_dir: Path, manifest=None) -> list[str]:
    manifest = manifest or load_manifest(csv_dir)
    controlled = controlled_sheets(manifest)
    return [
        str(entry["sheet_name"])
        for entry in manifest["sheets"]
        if str(entry["sheet_name"]) not in controlled
    ]


def duplicates(values: list[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def allocation_key(fields: list[str]) -> str:
    if ALLOCATION_ID in fields:
        return ALLOCATION_ID
    if DATA_ID in fields:
        return DATA_ID
    return ALLOCATION_ID


def check_core_ids(csv_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest = load_manifest(csv_dir)
    signals_sheet = resolve_signals_sheet(manifest)
    checks = [
        (SYSTEMS_SHEET, SYSTEM_UNIQUE_ID, "system"),
        (signals_sheet, SIGNAL_ID, "signal"),
        (DATABUSES_SHEET, BUS_ID, "bus"),
    ]
    for sheet_name, field, label in checks:
        _, rows = read_sheet(sheet_name, csv_dir, manifest)
        ids = collect_ids(rows, field)
        for value in duplicates(ids):
            errors.append(f"Duplicate {label} ID in {sheet_name}: {value}")
    return errors


def check_system_hierarchy(csv_dir: Path) -> list[str]:
    """Validate the 0_Systems containment tree and multiplicity conventions."""
    errors: list[str] = []
    _, rows = read_sheet(SYSTEMS_SHEET, csv_dir)

    unique_ids = {row.get(SYSTEM_UNIQUE_ID, "").strip() for row in rows}
    unique_ids.discard("")
    parent_of: dict[str, str] = {}
    no_instance_types = {"aircraft", "system", "domain"}

    for row in rows:
        unique_id = row.get(SYSTEM_UNIQUE_ID, "").strip()
        if not unique_id:
            errors.append(
                f"System row missing {SYSTEM_UNIQUE_ID} "
                f"({SYSTEM_TEXTUAL_NAME}={row.get(SYSTEM_TEXTUAL_NAME, '')!r})"
            )
            continue

        parent = (
            row.get(INSTALLED_IN) or row.get("Installed In") or ""
        ).strip()
        typ = (row.get("Type") or row.get("System Type") or "").strip()
        multiplicity = row.get("Multiplicity", "").strip()
        token = row.get("Instance Token", "").strip()
        parent_of[unique_id] = parent

        if parent and parent not in unique_ids:
            errors.append(f"System {unique_id}: unknown Installed In '{parent}'")
        if parent == unique_id:
            errors.append(f"System {unique_id}: Installed In refers to itself")

        if typ.lower() in no_instance_types:
            # Empty or "1" Multiplicity is fine; Instance Token is never allowed.
            if token or (multiplicity and multiplicity != "1"):
                errors.append(
                    f"{typ or 'System'} {unique_id} must have empty Multiplicity "
                    "(or '1') and no Instance Token"
                )
            continue

        if not multiplicity.isdigit() or int(multiplicity) < 1:
            errors.append(
                f"System {unique_id}: Multiplicity '{multiplicity}' is not a "
                "positive integer (count per parent instance)"
            )
            continue
        count = int(multiplicity)
        if count > 1 and not token:
            errors.append(
                f"System {unique_id}: Multiplicity {count} requires an Instance Token"
            )
        if count == 1 and token and parent:
            errors.append(
                f"System {unique_id}: singleton must not carry an Instance Token "
                f"'{token}' (it adds nothing to the instance path)"
            )

    for unique_id in parent_of:
        seen: set[str] = set()
        node = parent_of.get(unique_id, "")
        while node:
            if node in seen:
                errors.append(f"System {unique_id}: containment cycle via {node}")
                break
            seen.add(node)
            node = parent_of.get(node, "")
    return errors


def check_system_references(csv_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest = load_manifest(csv_dir)
    tree = SystemTree.load(csv_dir, manifest)
    signals_sheet = resolve_signals_sheet(manifest)

    targets = [
        (
            signals_sheet,
            SIGNAL_ID,
            [INTERFACING_EQUIPMENT, SIGNAL_OWNER, REPEATED_PER],
        ),
        (
            DATABUSES_SHEET,
            BUS_ID,
            [WRITER, RECEIVER, "master_lru", "equipment_connected"],
        ),
    ]
    targets += [
        (
            sheet,
            allocation_key(read_sheet(sheet, csv_dir, manifest)[0]),
            [WRITER_LRU, RECEIVER_LRUS],
        )
        for sheet in payload_sheets(csv_dir, manifest)
    ]

    for sheet, id_field, fields in targets:
        available, rows = read_sheet(sheet, csv_dir, manifest)
        for row in rows:
            row_id = row.get(id_field, "").strip() or "?"
            for field in fields:
                if field not in available:
                    continue
                for acronym in split_refs(row.get(field, "")):
                    if acronym in PLACEHOLDERS:
                        continue
                    # Writer/Receiver on buses may be instance tokens (FCC-1).
                    base = acronym.split("-")[0] if "-" in acronym else acronym
                    if acronym in tree.acronyms or base in tree.acronyms:
                        continue
                    if field in {WRITER, RECEIVER, WRITER_LRU, RECEIVER_LRUS}:
                        # Instance tokens are validated loosely against acronym prefixes.
                        if any(
                            acronym.startswith(f"{a}-") or acronym == a
                            for a in tree.acronyms
                        ):
                            continue
                    errors.append(
                        f"{sheet} {row_id}: {field} '{acronym}' is not in {SYSTEMS_SHEET}"
                    )
    return errors


def check_signal_and_payload_refs(csv_dir: Path) -> list[str]:
    errors: list[str] = []
    warnings_holder: list[str] = []
    manifest = load_manifest(csv_dir)
    signals_sheet = resolve_signals_sheet(manifest)
    _, signals = read_sheet(signals_sheet, csv_dir, manifest)
    signal_ids = set(collect_ids(signals, SIGNAL_ID))

    for row in signals:
        sid = row.get(SIGNAL_ID, "").strip() or "?"
        iface = (row.get(INTERFACE_TYPE) or "").strip()
        if iface and iface not in INTERFACE_TYPES:
            warnings_holder.append(
                f"{signals_sheet} {sid}: {INTERFACE_TYPE} '{iface}' is not one of "
                f"{', '.join(INTERFACE_TYPES)}"
            )
        for ref in split_refs(row.get(RELATED_TO, "")):
            if ref not in signal_ids:
                errors.append(
                    f"{signals_sheet} {sid}: {RELATED_TO} '{ref}' is not a known "
                    f"{SIGNAL_ID}"
                )
            elif ref == sid:
                errors.append(
                    f"{signals_sheet} {sid}: {RELATED_TO} must not reference itself"
                )

    _, buses = read_sheet(DATABUSES_SHEET, csv_dir, manifest)
    for row in buses:
        bus_id = row.get(BUS_ID, "").strip() or "?"
        topo = (row.get(TOPOLOGY) or "").strip()
        if topo and topo not in BUS_TOPOLOGIES and not normalize_bus_topology(topo):
            warnings_holder.append(
                f"{DATABUSES_SHEET} {bus_id}: {TOPOLOGY} '{topo}' is not one of "
                f"{', '.join(BUS_TOPOLOGIES)}"
            )
        elif topo and topo not in BUS_TOPOLOGIES and normalize_bus_topology(topo):
            warnings_holder.append(
                f"{DATABUSES_SHEET} {bus_id}: {TOPOLOGY} '{topo}' should be "
                f"formalized as '{formal_topology_label(topo)}'"
            )

    for sheet in payload_sheets(csv_dir, manifest):
        fields, rows = read_sheet(sheet, csv_dir, manifest)
        key = allocation_key(fields)
        for row in rows:
            row_id = row.get(key, "").strip() or "?"
            sid = row.get(SIGNAL_ID_REF, "").strip()
            if not sid:
                warnings_holder.append(
                    f"{sheet} {row_id}: missing {SIGNAL_ID_REF}, so this allocation "
                    "cannot be traced"
                )
                continue
            if sid not in signal_ids:
                errors.append(
                    f"{sheet} {row_id}: {SIGNAL_ID_REF} '{sid}' is not a known "
                    f"{SIGNAL_ID}"
                )
            if ";" in sid:
                errors.append(
                    f"{sheet} {row_id}: {SIGNAL_ID_REF} must reference exactly one "
                    f"{SIGNAL_ID}"
                )
    # Warnings are returned via a module-level pattern in run_checks.
    check_signal_and_payload_refs.last_warnings = warnings_holder  # type: ignore[attr-defined]
    return errors


check_signal_and_payload_refs.last_warnings = []  # type: ignore[attr-defined]


def check_allocation_ids(csv_dir: Path) -> list[str]:
    """Allocation Id must be unique within each tab and workbook-wide."""
    errors: list[str] = []
    manifest = load_manifest(csv_dir)
    workbook_ids: list[str] = []
    for sheet_name in payload_sheets(csv_dir, manifest):
        fields, rows = read_sheet(sheet_name, csv_dir, manifest)
        key = allocation_key(fields)
        if key not in fields:
            errors.append(
                f"{sheet_name}: missing {ALLOCATION_ID} / {DATA_ID} column"
            )
            continue
        sheet_ids = collect_ids(rows, key)
        for value in duplicates(sheet_ids):
            errors.append(f"Duplicate allocation ID in {sheet_name}: {value}")
        workbook_ids.extend(sheet_ids)
    for value in duplicates(workbook_ids):
        errors.append(
            f"Duplicate {ALLOCATION_ID} across bus-definition tabs: {value}"
        )
    return errors


def check_bus_families(csv_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest = load_manifest(csv_dir)
    fields, buses = read_sheet(DATABUSES_SHEET, csv_dir, manifest)
    if "instance" not in fields and BUS_DEFINITION not in fields:
        # Current export uses Bus Definition without a separate instance column.
        pass
    families = family_map(buses)
    for name, members in families.items():
        if not members:
            errors.append(f"Bus family '{name}' has no members")
    return errors


def run_checks(csv_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    errors.extend(check_core_ids(csv_dir))
    errors.extend(check_system_hierarchy(csv_dir))
    errors.extend(check_system_references(csv_dir))
    errors.extend(check_signal_and_payload_refs(csv_dir))
    errors.extend(check_allocation_ids(csv_dir))
    errors.extend(check_bus_families(csv_dir))
    warnings = list(check_signal_and_payload_refs.last_warnings)  # type: ignore[attr-defined]
    return errors, warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate ICD CSV integrity (Systems, Signals, allocations)."
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=DEFAULT_CSV_DIR,
        help=f"CSV directory (default: {DEFAULT_CSV_DIR})",
    )
    parser.add_argument(
        "--quiet-warnings",
        action="store_true",
        help="Report the warning count only, without listing each item",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    csv_dir = args.csv_dir.resolve()
    errors, warnings = run_checks(csv_dir)

    if warnings:
        print(f"Warnings ({len(warnings)}):")
        if args.quiet_warnings:
            print("  (use the default output to list them)")
        else:
            for warning in warnings:
                print(f"  ! {warning}")

    if errors:
        print(f"Integrity check FAILED ({len(errors)} issue(s)):")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(
        "Integrity check OK: Systems, Signals and bus allocations are consistent."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
