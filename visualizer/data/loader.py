"""Load ICD CSVs into pandas DataFrames and precompute graph edges."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from visualizer.data.models import (
    ALLOCATION_ID,
    CONTROLLED_SHEETS,
    DATABUSES_SHEET,
    SIGNAL_ID,
    SIGNALS_SHEET,
    SYSTEMS_SHEET,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _PROJECT_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from icd_csv import load_manifest, read_sheet, sheet_index  # noqa: E402
from icd_instances import SystemTree  # noqa: E402
from icd_paths import DEFAULT_CSV_DIR  # noqa: E402
from icd_sheets import (  # noqa: E402
    TOPOLOGY_ANALOG,
    TOPOLOGY_DISCRETE,
    TOPOLOGY_POWER,
    TOPOLOGY_SHARED,
    TOPOLOGY_UNIDIRECTIONAL,
    normalize_bus_topology,
)


def resolve_signals_sheet(manifest: dict) -> str:
    """Return the catalog sheet name present in the workbook."""
    index = sheet_index(manifest)
    if SIGNALS_SHEET in index:
        return SIGNALS_SHEET
    raise KeyError(f"{SIGNALS_SHEET} not found in workbook manifest")


def csv_mtime_key(csv_dir: Path | None = None) -> str:
    """Hash of CSV mtimes so Streamlit cache invalidates on export changes."""
    csv_dir = csv_dir or DEFAULT_CSV_DIR
    parts: list[str] = []
    for path in sorted(csv_dir.glob("*.csv")):
        parts.append(f"{path.name}:{path.stat().st_mtime_ns}")
    manifest = csv_dir / "_workbook_manifest.json"
    if manifest.is_file():
        parts.append(f"manifest:{manifest.stat().st_mtime_ns}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def _sheet_to_df(sheet_name: str, csv_dir: Path, manifest: dict) -> pd.DataFrame:
    fields, rows = read_sheet(sheet_name, csv_dir, manifest)
    if not rows:
        return pd.DataFrame(columns=fields)
    return pd.DataFrame(rows)


def _split_ids(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def _normalize_payload(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize allocation PK and signal identity columns."""
    work = frame.copy()
    if ALLOCATION_ID not in work.columns and "Data Id" in work.columns:
        work = work.rename(columns={"Data Id": ALLOCATION_ID})
    elif ALLOCATION_ID not in work.columns and "data_id" in work.columns:
        work = work.rename(columns={"data_id": ALLOCATION_ID})
    if "signal_id" not in work.columns and SIGNAL_ID in work.columns:
        work = work.rename(columns={SIGNAL_ID: "signal_id"})
    return work


@dataclass
class IcdBundle:
    systems: pd.DataFrame
    signals: pd.DataFrame
    buses: pd.DataFrame
    bus_payload: pd.DataFrame
    graph_nodes: pd.DataFrame
    graph_edges: pd.DataFrame
    generic_nodes: pd.DataFrame
    generic_edges: pd.DataFrame
    csv_dir: Path
    signals_sheet: str


def load_icd(mtime_key: str = "", csv_dir: Path | None = None) -> IcdBundle:
    """Load and join the ICD working set. ``mtime_key`` is a cache buster."""
    _ = mtime_key
    csv_dir = Path(csv_dir) if csv_dir else DEFAULT_CSV_DIR
    manifest = load_manifest(csv_dir)
    signals_sheet = resolve_signals_sheet(manifest)

    systems = _sheet_to_df(SYSTEMS_SHEET, csv_dir, manifest)
    signals = _sheet_to_df(signals_sheet, csv_dir, manifest)
    buses = _sheet_to_df(DATABUSES_SHEET, csv_dir, manifest)
    if not buses.empty:
        buses = buses.copy()
        if "Bus Definition" in buses.columns and "definition_tab" not in buses.columns:
            buses["definition_tab"] = buses["Bus Definition"]

    controlled = set(CONTROLLED_SHEETS) | {signals_sheet}
    payload_frames: list[pd.DataFrame] = []
    for entry in manifest["sheets"]:
        sheet_name = str(entry["sheet_name"])
        if sheet_name in controlled:
            continue
        frame = _sheet_to_df(sheet_name, csv_dir, manifest)
        if frame.empty:
            continue
        frame = _normalize_payload(frame)
        frame["definition_tab"] = sheet_name
        payload_frames.append(frame)

    bus_payload = (
        pd.concat(payload_frames, ignore_index=True, sort=False)
        if payload_frames
        else pd.DataFrame()
    )

    if not bus_payload.empty and not signals.empty and SIGNAL_ID in signals.columns:
        signal_index = signals.set_index(SIGNAL_ID)
        phys_map = (
            signal_index["Physical Id"].to_dict()
            if "Physical Id" in signal_index.columns
            else {}
        )
        owner_map = (
            signal_index["Signal Owner"].to_dict()
            if "Signal Owner" in signal_index.columns
            else {}
        )
        role_map = (
            signal_index["Signal Role"].to_dict()
            if "Signal Role" in signal_index.columns
            else {}
        )

        def derive_physical(row: pd.Series) -> str:
            sid = str(row.get("signal_id") or "").strip()
            return str(phys_map.get(sid, "") or "")

        def hop_role(row: pd.Series) -> str:
            sid = str(row.get("signal_id") or "").strip()
            if not sid:
                return "unlinked"
            role = str(role_map.get(sid, "") or "").strip()
            writer = str(row.get("writer_lru") or "").strip()
            owners = {
                part.strip()
                for part in str(owner_map.get(sid, "") or "").split(";")
                if part.strip()
            }
            if role == "Command":
                return "command"
            if role == "Computed":
                if writer and owners and writer not in owners:
                    return "relay"
                return "computed"
            if role in {"Measurement", "Power"}:
                if writer and owners and writer in owners:
                    return "origin"
                if writer and owners and writer not in owners:
                    return "relay"
                return "origin"
            return "other"

        bus_payload = bus_payload.copy()
        bus_payload["derived_physical_id"] = bus_payload.apply(derive_physical, axis=1)
        bus_payload["hop_role"] = bus_payload.apply(hop_role, axis=1)

    graph_nodes, graph_edges = _build_graph(buses, bus_payload, signals, systems)
    generic_nodes, generic_edges = _build_generic_graph(
        buses, bus_payload, signals, systems
    )
    return IcdBundle(
        systems=systems,
        signals=signals,
        buses=buses,
        bus_payload=bus_payload,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        generic_nodes=generic_nodes,
        generic_edges=generic_edges,
        csv_dir=csv_dir,
        signals_sheet=signals_sheet,
    )


def _base_acronym(token: str) -> str:
    """Strip trailing ``-N`` instance suffixes to recover the system acronym."""
    text = str(token or "").strip()
    if not text:
        return ""
    parts = text.split("-")
    if len(parts) == 1:
        return text
    # Keep leading acronym; drop trailing numeric segments (FCC-1, BMU-1-1).
    while len(parts) > 1 and parts[-1].isdigit():
        parts.pop()
    return "-".join(parts) if parts else text


def _lru_tokens_for_acronym(
    existing: set[str],
    acronym: str,
    *,
    tree: SystemTree | None = None,
) -> list[str]:
    """Return instance tokens for ``acronym``.

    Prefer tokens already present on the graph (from ``10_Databuses``). Otherwise
    expand from the ``0_Systems`` tree so singletons under a multiplied ancestor
    become ``Acronym-1..N`` (e.g. ``GBX-1..4``).
    """
    acronym = str(acronym or "").strip()
    if not acronym:
        return []
    matches = sorted(
        tok
        for tok in existing
        if tok == acronym or tok.startswith(f"{acronym}-")
    )
    if matches:
        # Drop a lone bare acronym when instantiated siblings also exist.
        inst = [t for t in matches if t != acronym]
        return inst or matches
    if tree is not None:
        return tree.instance_tokens(acronym)
    return [acronym]


def _instance_suffix(token: str, acronym: str) -> str:
    token = str(token or "").strip()
    acronym = str(acronym or "").strip()
    if not token or not acronym:
        return ""
    if token == acronym:
        return ""
    if token.startswith(f"{acronym}-"):
        return token[len(acronym) + 1 :]
    return ""


def _index_path(suffix: str) -> tuple[int | str, ...]:
    """Parse ``1-08`` / ``1-8`` into a comparable index path ``(1, 8)``."""
    parts: list[int | str] = []
    for part in str(suffix or "").split("-"):
        if not part:
            continue
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part.lower())
    return tuple(parts)


def _pair_instance_tokens(
    left: list[str],
    right: list[str],
    left_acr: str,
    right_acr: str,
) -> list[tuple[str, str]]:
    """Pair instance endpoints that share an ancestor index path.

    - Equal-length paths (e.g. ``PACK-2-8`` ↔ ``BMU-2-8``): exclusive 1:1.
    - Prefix paths (e.g. ``HVPDU-2`` ↔ ``PACK-2-*`` / ``EMC-2-*``): many-to-one;
      every deeper child under that ancestor is linked.
    """
    if not left or not right:
        return []

    left_paths = {
        tok: _index_path(_instance_suffix(tok, left_acr)) for tok in left
    }
    right_paths = {
        tok: _index_path(_instance_suffix(tok, right_acr)) for tok in right
    }

    pairs: list[tuple[str, str]] = []
    used_left: set[str] = set()
    used_right: set[str] = set()

    # Phase 1 — exact path match (1:1).
    for a in left:
        sa = left_paths[a]
        if not sa:
            continue
        for b in right:
            if b in used_right:
                continue
            sb = right_paths[b]
            if sa and sb and sa == sb:
                pairs.append((a, b))
                used_left.add(a)
                used_right.add(b)
                break

    # Phase 2 — proper prefix match (many-to-one / one-to-many).
    for a in left:
        if a in used_left:
            continue
        sa = left_paths[a]
        if not sa:
            continue
        for b in right:
            if b in used_right:
                continue
            sb = right_paths[b]
            if not sb or sa == sb:
                continue
            if sa[: len(sb)] == sb or sb[: len(sa)] == sa:
                pairs.append((a, b))
                # Do not mark either side used: one HVPDU links all packs/EMCs.

    if pairs:
        return pairs

    # Both sides bare / unmatched: zip when counts match, else Cartesian.
    bare_left = [a for a in left if not left_paths[a]]
    bare_right = [b for b in right if not right_paths[b]]
    if bare_left and bare_right and len(bare_left) == len(bare_right):
        return list(zip(bare_left, bare_right, strict=False))
    if len(left) == len(right):
        return list(zip(left, right, strict=False))
    return [(a, b) for a in left for b in right]


def _add_interface_links_from_signals(
    *,
    signals: pd.DataFrame,
    nodes: dict[str, dict[str, str]],
    edges: list[dict[str, str]],
    seen_edges: set[tuple[str, str, str]],
    instantiate: bool,
    systems: pd.DataFrame | None = None,
) -> None:
    """Add Analog / Discrete / Power links when Physical System ≠ Signal Owner."""
    if signals.empty:
        return
    for col in ("Physical System", "Signal Owner", "Interface Type"):
        if col not in signals.columns:
            return

    existing_lrus = {
        nid for nid, meta in nodes.items() if meta.get("kind") == "lru"
    }
    tree: SystemTree | None = None
    if instantiate and systems is not None and not systems.empty:
        tree = SystemTree(systems.to_dict("records"))

    def add_node(
        node_id: str,
        kind: str,
        label: str = "",
        *,
        bus_mode: str = "",
        family: str = "",
    ) -> None:
        if not node_id or node_id in {"N/A", "TBD"}:
            return
        if node_id not in nodes:
            nodes[node_id] = {
                "node_id": node_id,
                "kind": kind,
                "label": label or node_id,
                "bus_mode": bus_mode,
                "family": family or (node_id if kind == "bus" else ""),
            }
            return
        if kind == "bus" and bus_mode and not nodes[node_id].get("bus_mode"):
            nodes[node_id]["bus_mode"] = bus_mode

    def add_edge(
        source: str,
        target: str,
        edge_type: str,
        bus_id: str,
        *,
        link_kind: str,
        signal_ref: str = "",
    ) -> None:
        key = (source, target, edge_type)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(
            {
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "bus_id": bus_id,
                "data_id": "",
                "signal_ref": signal_ref,
                "link_kind": link_kind,
            }
        )

    for _, row in signals.iterrows():
        iface = normalize_bus_topology(row.get("Interface Type"))
        if iface not in {TOPOLOGY_ANALOG, TOPOLOGY_DISCRETE, TOPOLOGY_POWER}:
            continue
        physical = str(row.get("Physical System") or "").strip()
        owner = str(row.get("Signal Owner") or "").strip()
        if not physical or not owner or physical == owner:
            continue
        role = str(row.get("Signal Role") or "").strip()
        sid = str(row.get(SIGNAL_ID) or row.get("Signal Id") or "").strip()

        if instantiate:
            phys_tokens = _lru_tokens_for_acronym(
                existing_lrus, physical, tree=tree
            )
            owner_tokens = _lru_tokens_for_acronym(
                existing_lrus, owner, tree=tree
            )
        else:
            phys_tokens = [physical]
            owner_tokens = [owner]

        # Measurement / default: physical -> owner. Command: owner -> physical.
        if role == "Command":
            left_acr, right_acr = owner, physical
            left_tokens, right_tokens = owner_tokens, phys_tokens
        else:
            left_acr, right_acr = physical, owner
            left_tokens, right_tokens = phys_tokens, owner_tokens

        pairs = _pair_instance_tokens(
            left_tokens, right_tokens, left_acr, right_acr
        )
        for writer, receiver in pairs:
            # Direct LRU↔LRU edge — color carries Analog/Discrete/Power; no hub node.
            add_node(writer, "lru")
            add_node(receiver, "lru")
            add_edge(
                writer,
                receiver,
                "iface",
                "",
                link_kind=iface,
                signal_ref=sid,
            )
            existing_lrus.add(writer)
            existing_lrus.add(receiver)


def _annotate_edge_link_kinds(
    nodes: dict[str, dict[str, str]], edges: list[dict[str, str]]
) -> None:
    """Stamp each edge with the owning bus topology (color source of truth)."""
    for edge in edges:
        if edge.get("link_kind"):
            continue
        bus_id = str(edge.get("bus_id") or "").strip()
        mode = ""
        if bus_id and bus_id in nodes:
            mode = str(nodes[bus_id].get("bus_mode") or "")
        if not mode:
            # Fall back to whichever endpoint is a bus.
            for end in (edge.get("source"), edge.get("target")):
                meta = nodes.get(str(end or ""), {})
                if meta.get("kind") == "bus":
                    mode = str(meta.get("bus_mode") or "")
                    break
        edge["link_kind"] = mode or TOPOLOGY_UNIDIRECTIONAL


def _graph_frames(
    nodes: dict[str, dict[str, str]], edges: list[dict[str, str]]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    _annotate_edge_link_kinds(nodes, edges)
    nodes_df = (
        pd.DataFrame(list(nodes.values()))
        if nodes
        else pd.DataFrame(columns=["node_id", "kind", "label", "bus_mode", "family"])
    )
    edges_df = (
        pd.DataFrame(edges)
        if edges
        else pd.DataFrame(
            columns=[
                "source",
                "target",
                "edge_type",
                "bus_id",
                "data_id",
                "signal_ref",
                "link_kind",
            ]
        )
    )
    return nodes_df, edges_df


def _build_generic_graph(
    buses: pd.DataFrame,
    bus_payload: pd.DataFrame,
    signals: pd.DataFrame | None = None,
    systems: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One node per Bus Definition; bare (non-instantiated) LRU acronyms.

    Writer/Receiver endpoints are collapsed to system acronyms. Analog /
    Discrete / Power links are direct LRU↔LRU edges between those acronyms.
    """
    _ = systems
    nodes: dict[str, dict[str, str]] = {}
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(
        node_id: str,
        kind: str,
        label: str = "",
        *,
        bus_mode: str = "",
        family: str = "",
    ) -> None:
        if not node_id or node_id in {"N/A", "TBD"}:
            return
        if node_id not in nodes:
            nodes[node_id] = {
                "node_id": node_id,
                "kind": kind,
                "label": label or node_id,
                "bus_mode": bus_mode,
                "family": family or (node_id if kind == "bus" else ""),
            }
            return
        if kind == "bus" and bus_mode:
            current = nodes[node_id].get("bus_mode", "")
            if current != TOPOLOGY_SHARED and bus_mode == TOPOLOGY_SHARED:
                nodes[node_id]["bus_mode"] = TOPOLOGY_SHARED
            elif not current:
                nodes[node_id]["bus_mode"] = bus_mode

    def add_edge(source: str, target: str, edge_type: str, bus_id: str) -> None:
        key = (source, target, edge_type)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(
            {
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "bus_id": bus_id,
                "data_id": "",
                "signal_ref": "",
                "link_kind": "",
            }
        )

    if not buses.empty:
        for _, row in buses.iterrows():
            family = str(
                row.get("definition_tab") or row.get("Bus Definition") or ""
            ).strip()
            if not family:
                continue
            writers = [_base_acronym(w) for w in _split_ids(row.get("Writer"))]
            receivers = [_base_acronym(r) for r in _split_ids(row.get("Receiver"))]
            mode = classify_bus_mode(row.get("topology"), writers, receivers)
            add_node(family, "bus", family, bus_mode=mode, family=family)

    if not bus_payload.empty:
        for _, row in bus_payload.iterrows():
            family = str(row.get("definition_tab") or "").strip()
            if not family:
                continue
            add_node(family, "bus", family, family=family)
            for writer in _split_ids(row.get("writer_lru")):
                acr = _base_acronym(writer)
                add_node(acr, "lru")
                add_edge(acr, family, "writes", family)
            for receiver in _split_ids(row.get("receiver_lrus")):
                acr = _base_acronym(receiver)
                add_node(acr, "lru")
                add_edge(family, acr, "reads", family)

    for node_id, meta in list(nodes.items()):
        if meta.get("kind") != "bus" or meta.get("bus_mode"):
            continue
        writers = {
            e["source"]
            for e in edges
            if e["target"] == node_id and e["edge_type"] == "writes"
        }
        receivers = {
            e["target"]
            for e in edges
            if e["source"] == node_id and e["edge_type"] == "reads"
        }
        meta["bus_mode"] = (
            TOPOLOGY_SHARED if writers & receivers else TOPOLOGY_UNIDIRECTIONAL
        )

    _add_interface_links_from_signals(
        signals=signals if signals is not None else pd.DataFrame(),
        nodes=nodes,
        edges=edges,
        seen_edges=seen_edges,
        instantiate=False,
        systems=None,
    )
    return _graph_frames(nodes, edges)


def classify_bus_mode(
    topology: object, writers: list[str], receivers: list[str]
) -> str:
    """Return a formal topology key for a digital bus row."""
    key = normalize_bus_topology(topology)
    if key in {
        TOPOLOGY_UNIDIRECTIONAL,
        TOPOLOGY_SHARED,
        TOPOLOGY_ANALOG,
        TOPOLOGY_DISCRETE,
        TOPOLOGY_POWER,
    }:
        return key
    writer_set = set(writers)
    receiver_set = set(receivers)
    if writer_set & receiver_set:
        return TOPOLOGY_SHARED
    return TOPOLOGY_UNIDIRECTIONAL


def _build_graph(
    buses: pd.DataFrame,
    bus_payload: pd.DataFrame | None = None,
    signals: pd.DataFrame | None = None,
    systems: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Full-network graph: physical bus + LRU instances from Writer/Receiver."""
    _ = bus_payload
    nodes: dict[str, dict[str, str]] = {}
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(
        node_id: str,
        kind: str,
        label: str = "",
        *,
        bus_mode: str = "",
        family: str = "",
    ) -> None:
        if not node_id or node_id in {"N/A", "TBD"}:
            return
        if node_id not in nodes:
            nodes[node_id] = {
                "node_id": node_id,
                "kind": kind,
                "label": label or node_id,
                "bus_mode": bus_mode,
                "family": family,
            }
            return
        if kind == "bus" and bus_mode and not nodes[node_id].get("bus_mode"):
            nodes[node_id]["bus_mode"] = bus_mode
        if kind == "bus" and family and not nodes[node_id].get("family"):
            nodes[node_id]["family"] = family

    if not buses.empty:
        for _, row in buses.iterrows():
            bus_id = str(row.get("Bus Id") or "").strip()
            if not bus_id:
                continue
            writers = _split_ids(row.get("Writer")) or _split_ids(
                row.get("equipment_connected")
            )
            receivers = _split_ids(row.get("Receiver"))
            if not receivers and "equipment_connected" in row.index:
                receivers = [
                    e
                    for e in _split_ids(row.get("equipment_connected"))
                    if e not in writers
                ]
            family = str(
                row.get("definition_tab") or row.get("Bus Definition") or ""
            ).strip()
            mode = classify_bus_mode(row.get("topology"), writers, receivers)
            add_node(
                bus_id,
                "bus",
                str(row.get("name") or bus_id),
                bus_mode=mode,
                family=family,
            )
            for lru in writers:
                add_node(lru, "lru")
                edges.append(
                    {
                        "source": lru,
                        "target": bus_id,
                        "edge_type": "writes",
                        "bus_id": bus_id,
                        "data_id": "",
                        "signal_ref": "",
                        "link_kind": mode,
                    }
                )
                seen_edges.add((lru, bus_id, "writes"))
            for lru in receivers:
                add_node(lru, "lru")
                edges.append(
                    {
                        "source": bus_id,
                        "target": lru,
                        "edge_type": "reads",
                        "bus_id": bus_id,
                        "data_id": "",
                        "signal_ref": "",
                        "link_kind": mode,
                    }
                )
                seen_edges.add((bus_id, lru, "reads"))

    _add_interface_links_from_signals(
        signals=signals if signals is not None else pd.DataFrame(),
        nodes=nodes,
        edges=edges,
        seen_edges=seen_edges,
        instantiate=True,
        systems=systems,
    )
    return _graph_frames(nodes, edges)


def payloads_for_signal(bundle: IcdBundle, *, signal_id: str = "") -> pd.DataFrame:
    """All bus-definition allocations sharing a canonical signal_id."""
    frame = bundle.bus_payload
    if frame.empty or not signal_id:
        return frame.iloc[0:0].copy() if not frame.empty else frame
    if "signal_id" not in frame.columns:
        return frame.iloc[0:0].copy()
    mask = frame["signal_id"].fillna("").astype(str).str.strip() == signal_id
    return frame.loc[mask].copy()
