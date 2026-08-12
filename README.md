# SignalCraft

SignalCraft is the tooling for the ICD signal database: Excel ↔ CSV export,
JSON edits, integrity checks, and a Streamlit visualizer.

## Install

### 1. Install uv

SignalCraft uses [uv](https://docs.astral.sh/uv/) for Python and dependencies.
Install once if you do not already have it.

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Open a **new** terminal so `PATH` picks up uv, then check:

```powershell
uv --version
```

Alternatives: [WinGet](https://docs.astral.sh/uv/getting-started/installation/) (`winget install --id=astral-sh.uv -e`) or the [uv install docs](https://docs.astral.sh/uv/getting-started/installation/).

### 2. Sync the project

From the SignalCraft repo root:

```powershell
cd C:\path\to\SignalCraft
uv sync
```

This creates `.venv` and installs the locked dependencies (`pyproject.toml` / `uv.lock`). Python ≥ 3.11.

## Source of truth

`ICD_Database.xlsx` is the source of truth for the signal database.

Tooling lives in `scripts/`. Generated CSV files under `csv/` are the working
set for tools and AI. Two controlled sheets are documentation, not payload:

| Sheet / CSV | Role |
|---|---|
| `README` (`01_README.csv`) | Model rules, instance naming, Signal Role philosophy |
| `Column_Help` (`02_Column_Help.csv`) | Per-column description and allowed values |

The aircraft ICD content in `1_Signals`, `10_Databuses` and the bus-definition
tabs is growing more technical detail, but **most values remain working
assumptions / placeholders**. The priority for now is a stable schema and
tooling so the database format and editors can keep progressing; treat rates,
bit positions, encodings and many notes as provisional until supplier designs
are locked.

## Routine workflow

Run every command from the repo root with `uv run` (or the `.bat` wrappers, which call `uv run`).

```powershell
# 1. Export Excel to CSV
uv run python .\scripts\excel_to_csv.py

# 2. Edit the CSV working set (upsert / delete / rewrite JSON)
uv run python .\scripts\icd_edit.py --json .\scripts\examples\edit_upsert_signal.example.json --dry-run
uv run python .\scripts\icd_edit.py --json .\scripts\examples\edit_upsert_signal.example.json

# 3. Check integrity (IDs, references, allocations)
uv run python .\scripts\database_integrity_check.py

# 4. Rebuild a review workbook (does not overwrite ICD_Database.xlsx)
uv run python .\scripts\csv_to_excel.py
```

Windows shortcuts (same scripts, via uv): `excel_to_csv.bat`, `csv_to_excel.bat`.

Or use **Edit data** in the visualizer (same JSON API, guided forms).

## Visualizer

```powershell
uv run streamlit run visualizer/app.py
```

See [`visualizer/README.md`](visualizer/README.md) for page descriptions. The visualizer reads the `csv/` working set (not Excel).

After review, copy approved content into `ICD_Database.xlsx`, or replace the
source workbook manually when ready.

## Scripts

### CLIs

| Script | Role |
|---|---|
| `scripts/excel_to_csv.py` | Export every workbook tab to `csv/` |
| `scripts/icd_edit.py` | Blind upsert/delete/rewrite JSON edits with preflight |
| `scripts/database_integrity_check.py` | Validate IDs, system references and signal allocations |
| `scripts/csv_to_excel.py` | Rebuild `ICD_Database_rebuilt.xlsx` from CSV |
| `scripts/reorder_sheets.py` | Renumber the CSV file prefixes to the reading order |
| `visualizer/` | Streamlit visualizer (`uv run streamlit run visualizer/app.py`) |

### Libraries (imported by CLIs / visualizer; not runnable)

| Module | Role |
|---|---|
| `scripts/icd_instances.py` | Derive instance tokens and totals from the `0_Systems` tree |
| `scripts/icd_edit_lib.py` | Edit engine shared by `icd_edit.py` and the visualizer |
| `scripts/icd_csv.py` | Manifest and per-sheet CSV read/write |
| `scripts/icd_paths.py` | Default workbook / `csv/` / rebuilt paths |
| `scripts/icd_sheets.py` | Sheet names and controlled vocabulary |

The integrity check separates two levels. **Errors** are broken data: unknown
identifiers, UniqueIds missing from `0_Systems`, allocations whose `signal_id`
is not in `1_Signals`, or duplicate `Allocation Id` values (per tab and
workbook-wide). **Warnings** are known gaps that must not block the workflow
(for example a payload row missing `signal_id`). Use `--quiet-warnings` for the
count only.

### Edit JSON (`icd_edit.py`)

One document drives the full working set:

```json
{
  "rewrite": {
    "acronyms": [{ "from": "HICU", "to": "HCU" }],
    "ids": [{ "from": "SIG-010", "to": "SIG-210" }]
  },
  "upsert": {
    "1_Signals": [{ "Signal Id": "SIG-001", "Signal Name": "…" }]
  },
  "delete": { "IRU_TX": ["DBUS-099"] },
  "options": { "with_buses": true }
}
```

- **Omitted field** → leave unchanged. **Explicit `""`** → clear.
- Upsert matches on the sheet primary key; omit the key to auto-allocate (`SIG` / `DBUS` / …). `0_Systems` requires an explicit `UniqueId` (no auto-id).
- Payload sheets use `Allocation Id` + `signal_id` (`SIG-*`).
- `rewrite.acronyms` renames a `0_Systems.UniqueId` and propagates it across references; `rewrite.ids` renames Signal/Bus/allocation ids.
- If a multiplicity change impacts bus families and `options.with_buses` is omitted, the edit **aborts** until you set `true` (clone/remove buses) or `false` (systems only).

Examples: `scripts/examples/edit_*.example.json`.

## Canonical model

```text
0_Systems  →  1_Signals  →  10_Databuses
                   ↓
          Bus-definition tabs (signal_id → SIG-*)
```

Fill in that order: systems first (`UniqueId`), then signals, then buses, then
allocations. Relays reuse the same `SIG-*` on several allocations — do **not**
duplicate the signal row.

`0_Systems` is a containment tree of **kinds** of equipment (not instances).
`1_Signals` is the canonical logical catalog. `10_Databuses` lists physical bus
instances. Bus-definition tabs (e.g. `NAC_CTRL`, `IRU_TX`) own transport:
message id, bit range, rate and encoding for each allocation.

## How to fill the database

Authoritative detail lives in the workbook sheets `README` and `Column_Help`
(also under `csv/`). This section is the short form for day-to-day fills.

### 1. `0_Systems` — equipment list and containment

Add a row **before** using a new UniqueId elsewhere. Use the exact `UniqueId`
everywhere else.

| Column | What to enter |
|---|---|
| `UniqueId` | Stable unique key used as the reference everywhere (`FCC`, `NAC`, …) |
| `Textual Name` | Human-readable equipment or grouping name |
| `Installed In/Part of` | Containment parent UniqueId (empty for aircraft root / functional-only rows) |
| `Functional system` | Optional grouping for review/display only — **not** used for instances |
| `Type` | `Aircraft` / `System` / `Zone` = hierarchy or labels; `Component` / `Controller` = real LRUs |
| `Multiplicity` | Count **per parent instance** (not aircraft total) |
| `Instance Token` | What this level adds to the path when Mult > 1: `{n}`, `{nn}`, or a fixed list. Empty if Mult = 1 |
| `Description` / `Notes` | Free text (notes describe current state, not change history) |

Aircraft totals = product of multiplicities up the tree. A singleton under a
multiplied parent (e.g. one GBX per nacelle) needs no token of its own; tools
derive `GBX-1`…`GBX-4` from the parent.

### Instance naming (for `10_Databuses` Writer / Receiver)

`0_Systems` never stores instances, but bus rows must name them. Build each
name mechanically:

**instance name = base UniqueId + one ordinal per multiplicative ancestor
(including the row itself), outermost first, hyphen-separated.** Levels with
Multiplicity 1 contribute nothing. Fixed-list tokens use list position as the
ordinal (`LVPDU_AFT` → `LVPDU-1`).

Examples: `HICU-3`, `EMC-1-2`, `BMU-1-7`, `BTMS-2`, `FCC-2`, bare `IRU`. There
is no aircraft-level index (never `EM-4` for “fourth motor on the aircraft”).

### 2. `1_Signals` — one row per logical signal

| Column | What to enter |
|---|---|
| `Signal Id` | Stable `SIG-*` (never reuse) |
| `Physical Id` | Optional; set **only** when 2+ signals share the same physical meaning (not a foreign key). Leave blank otherwise |
| `Signal Name` / `Abbreviation` | Human labels |
| `Signal Role` | `Measurement` \| `Command` \| `Request` \| `Computed` \| `Power` |
| `Interfacing Equipment` | Equipment the quantity belongs to (`0_Systems` UniqueId); empty for Computed |
| `Signal Owner` | System that owns the path / computation |
| `Repeated Per` | Extra dimensions not already implied by owner/interfacing equipment (bare UniqueIds like `NAC` or `EM`, **not** `NAC-1`) |
| `Related to` | Optional `;`-separated related `SIG-*` |
| `Connection Type` | Free-text sensing / connection note |
| `Interface Type` | `Digital` \| `Analog` \| `Discrete` \| `Power` |
| `Unit` / `Functional Minimum` / `Functional Maximum` | Engineering unit and **functional** range of the quantity in service (independent of bus encoding; allocation `minimum`/`maximum` hold the wire range) |
| `Derivation` | How the owner produces the value (always for Computed; for Request when the sender computes it; empty when only relaying or for protocol fields) |
| `Notes` / platform flags | Current-state notes; `On aircraft ?` / `On FND ?` / `On Sim ?` |

#### Signal Role (direction)

| Role | Meaning | Direction | Typical Interface Type |
|---|---|---|---|
| **Measurement** | State acquired from sensing hardware (incl. crew levers / switches) | Interfacing Equipment → Owner | Analog / Discrete / Digital |
| **Command** | Hardwired drive of an effector or safety device | Owner → Interfacing Equipment | Analog / Discrete |
| **Request** | Setpoint / enable / mode asked of another controller over a bus | Owner → Interfacing Equipment | Digital |
| **Computed** | Value derived by the owner | (no physical interface) | Digital |
| **Power** | Electrical supply (one row, nominal energy direction) | Owner (source) → Interfacing Equipment (load) | Power |

Command vs Request: hardwired Analog/Discrete drive → **Command**; bus message
asking another controller to act → **Request**. A cockpit pushbutton wired to a
controller is a **Measurement** (state is read, nothing is driven).

Do **not** create one signal row per nacelle/pack instance when units only differ
by replication — multiplicity in `0_Systems` covers that. Separate rows only
when roles or technologies differ. Relays keep one `Signal Id` across hops.

### 3. `10_Databuses` — one row per physical bus instance

| Column | What to enter |
|---|---|
| `Bus Id` | Stable instance id (e.g. `NAC_CTRL_1`) |
| `name` / `bus_use` | Human label and short purpose |
| `Bus Definition` | Exact name of the payload tab for this family (`NAC_CTRL`, …) |
| `protocol` / `speed` | Transport and bit rate when known |
| `topology` | `Unidirectional` or `Shared` for digital buses (drives Bus Topology colors). Analog / Discrete / Power are non-digital kinds |
| `Writer` / `Receiver` | Connected LRU **instances** (naming rule above) |
| `notes` / platform flags | As needed |

Several bus instances may share one `Bus Definition` so the payload is authored
once. On a shared bus, Writer/Receiver list every node; each allocation names
only its actual producer and intended receivers (usually a subset).

`Message ID`, bit range, encoding and `update_period_ms` on the definition tab
are the inputs for bus load / bandwidth checks: each distinct `Message ID` on a
physical bus instance is one frame type. Where suppliers have not fixed rates,
`update_period_ms` may carry class defaults (working assumptions — see workbook
`README`).

### 4. Bus-definition tabs — allocations on a family

One sheet per `Bus Definition` value (e.g. `NAC_CTRL`, `IRU_TX`). Each row is
one encoded item on that family.

| Column | What to enter |
|---|---|
| `Allocation Id` | Stable row key (`DBUS-*`); **unique workbook-wide**, not only within the tab |
| `signal_id` | Exactly one `SIG-*` from `1_Signals` (relays: same id on each hop) |
| `data_name` | Human-readable name on this bus |
| `writer_lru` / `receiver_lrus` | Producer and intended receivers (nodes of every instance of this definition) |
| `instance_dimension` | Extra token when the bus instance alone is not enough (e.g. `PACK-{n}`, `EM-{n}`) |
| `Message ID` | Transport identity: A825/CAN DOC or arbitration id, or A429 label |
| `message_or_label` | Human message / frame name when useful |
| `start bit` / `stop bit` | Field bit range (MSB…LSB inclusive) |
| `encoding` / `unit` / `scale` / `resolution` / `minimum` / `maximum` | Wire encoding and engineering mapping; `minimum`/`maximum` are the **encoding** range on this bus (often wider than the functional range on `1_Signals`) |
| `update_period_ms` / `validity` | Refresh period and how the receiver judges validity |
| `notes` / platform flags | Current-state notes; applicability flags |

### Cross-cutting rules

- Prefer stable ids (`SIG-*`, `DBUS-*`, bus ids, `UniqueId`); rename display names freely.
- Cross-references use ids/UniqueIds, never Excel row numbers or formulas.
- Multiple values in one cell → semicolon-separated.
- Hop identity everywhere is **`signal_id`**.
- After edits: integrity check, then rebuild Excel for review; promote to
  `ICD_Database.xlsx` only when approved.
