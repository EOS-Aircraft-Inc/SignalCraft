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
set for tools and AI.

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
identifiers, UniqueIds missing from `0_Systems`, or allocations whose
`signal_id` is not in `1_Signals`. **Warnings** are known gaps that must not
block the workflow (for example a payload row missing `signal_id`). Use
`--quiet-warnings` for the count only.

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

Fill in that order: systems first (UniqueIds), then signals, then buses, then
allocations. Relays reuse the same `SIG-*` on several allocations — do not
duplicate the signal row.

## How to fill the database

Column-by-column guidance (including allowed values) also lives in the workbook
sheet `Column_Help`. It exports and rebuilds with the rest of the CSV working set.

### 1. `0_Systems` — equipment list and containment

Add a row **before** using a new UniqueId elsewhere. Use the exact `UniqueId`
everywhere else.

| Column | What to enter |
|---|---|
| `UniqueId` | Stable unique key used as the reference everywhere (`FCC`, `NAC`, …) |
| `Textual Name` | Human-readable equipment or grouping name |
| `Installed In/Part of` | Containment parent UniqueId (empty for root / functional rows) |
| `Functional system` | Optional grouping only — **not** used for instances |
| `Type` | `Aircraft` / `System` = labels (not bus equipment); `Component` / `Controller` / … = real LRUs |
| `Multiplicity` | Count **per parent instance** (not aircraft total) |
| `Instance Token` | What this level adds to the path: `{n}` (unpadded `1`…`10`…), `{nn}` (zero-padded), or a fixed list. Empty if Mult = 1 |

Aircraft totals = product of multiplicities up the tree. A singleton under a
multiplied parent (e.g. one GBX per nacelle) needs no token of its own; tools
derive `GBX-1`…`GBX-4` from the parent.

### 2. `1_Signals` — one row per logical signal

| Column | What to enter |
|---|---|
| `Signal Id` | Stable `SIG-*` (never reuse) |
| `Signal Name` / `Abbreviation` | Human labels |
| `Signal Role` | Measurement / Command / Computed / … |
| `Interface Type` | `Digital` \| `Analog` \| `Discrete` \| `Power` |
| `Physical System` | Equipment the quantity belongs to (`0_Systems` UniqueId) |
| `Signal Owner` | System that owns the signal path |
| `Repeated Per` | Extra dimensions if needed (bare UniqueIds like `NAC` or `EM`, **not** `NAC-1`) |
| `Related to` | Optional `;`-separated related `SIG-*` |
| `Physical Id` | Opaque grouping label only (not a foreign key) |

Direction of the physical interface:

- **Measurement** — Physical System → Signal Owner  
- **Command** — Signal Owner → Physical System  
- **Computed** — produced by Signal Owner  

Do **not** create one signal row per nacelle/pack instance when units only differ
by replication — multiplicity in `0_Systems` covers that. Separate rows only
when roles or technologies differ (e.g. control vs protection).

### 3. `10_Databuses` — one row per physical bus instance

| Column | What to enter |
|---|---|
| `Bus Id` | Stable instance id (e.g. `NAC_CTRL_1`) |
| `Bus Definition` | Name of the payload tab that defines this family’s data (`NAC_CTRL`, …) |
| `protocol` / `topology` | Protocol; topology `Unidirectional` or `Shared` (digital). Topology drives Bus Topology link color |
| `Writer` / `Receiver` | Connected LRUs — exact UniqueIds or instance tokens from `0_Systems` |
| platform flags | `On aircraft ?` / `On FND ?` / `On Sim ?` as needed |

Several bus instances may share one `Bus Definition` so the payload is authored
once. List all nodes on a shared bus in Writer/Receiver (and notes) as needed;
per-message producers/receivers live on the definition tab.

`Message ID`, bit range, encoding, `update_period_ms` and (for now) `offset=…`
in notes are the inputs for bus load / bandwidth checks: each distinct
`Message ID` on a physical bus instance is one frame type.

### 4. Bus-definition tabs — allocations on a family

One sheet per `Bus Definition` value (e.g. `NAC_CTRL`, `IRU_TX`). Each row is
one encoded item on that family.

| Column | What to enter |
|---|---|
| `Allocation Id` | Row key within the tab (`DBUS-*`) |
| `signal_id` | Exactly one `SIG-*` from `1_Signals` (relays: same id on each hop) |
| `data_name` | Human-readable name |
| `writer_lru` / `receiver_lrus` | Producer and intended receivers for this item |
| `instance_dimension` | Extra token when the bus instance alone is not enough (e.g. pack on a nacelle bus) |
| `Message ID` | Transport message identity: A825/CAN DOC or arbitration id, or A429 label |
| `message_or_label` | Human message / frame name when useful |
| `start bit` / `stop bit` | Field bit range (MSB…LSB as authored; inclusive) |
| encoding fields | unit, range, period, validity, … as known |
| platform flags | `On aircraft ?` / `On FND ?` / `On Sim ?` |

### Cross-cutting rules

- Prefer stable ids (`SYS-*`, `SIG-*`, `DBUS-*`, bus ids); rename names freely.
- Cross-references use ids/UniqueIds, never Excel row numbers or formulas.
- Multiple values in one cell → semicolon-separated.
- Hop identity everywhere is **`signal_id`**.
- After edits: integrity check, then rebuild Excel for review; promote to
  `ICD_Database.xlsx` only when approved.
