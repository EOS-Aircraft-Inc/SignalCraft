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

This creates `.venv` and installs the locked dependencies (`pyproject.toml` / `uv.lock`).

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

# 2. Edit the data — use the visualizer (below); it writes csv/ for you

# 3. Check integrity (IDs, references, allocations)
uv run python .\scripts\database_integrity_check.py

# 4. Rebuild a review workbook (does not overwrite ICD_Database.xlsx)
uv run python .\scripts\csv_to_excel.py
```

Windows shortcuts for steps 1 and 4: `excel_to_csv.bat`, `csv_to_excel.bat`.

Step 2 is the **Edit data** page of the visualizer — guided forms, with a
dry-run before anything is written.

## Visualizer

```powershell
uv run streamlit run visualizer/app.py
```

See [`visualizer/README.md`](visualizer/README.md) for page descriptions. The visualizer reads the `csv/` working set (not Excel).

## Maintaining the tool

Changing SignalCraft itself — adding a column, changing an allowed value,
editing the diagram, running the checks before committing — is covered
separately in [`DEVELOPERS.md`](DEVELOPERS.md). You do not need any of it to
fill in the database.

The rules a change has to respect — what belongs in the database, how signals
link, and the invariants the code relies on — are in
[`DECISIONS.md`](DECISIONS.md).

## Canonical model

```text
0_Systems  →  1_Signals  →  10_Databuses
                   ↓
          Bus-definition tabs (Signal Id)
```

Fill in that order: systems first (`UniqueId`), then signals, then buses, then
allocations. Relays reuse the same signals ID on several allocations — do **not**
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
| `Domain` | UniqueId of a `Type = Domain` row; review/display grouping only — **not** used for instances |
| `Type` | `Aircraft` / `Domain` / `Zone` = hierarchy or labels; `Component` = real LRUs. A `Domain` row declares a domain that other rows reference from their `Domain` column |
| `Multiplicity` | Count **per parent instance** (not aircraft total). Instance names follow from it — no separate token column |
| `Description` / `Notes` | Free text (notes describe current state, not change history) |

Aircraft totals = product of multiplicities up the tree. A singleton under a
multiplied parent (e.g. one GBX per nacelle) adds no ordinal of its own; tools
derive `GBX-1`…`GBX-4` from the parent.

### Instance naming (for `10_Databuses` Sender / Receiver)

`0_Systems` never stores instances, but bus rows must name them. Build each
name mechanically:

**instance name = base UniqueId + one ordinal per multiplicative ancestor
(including the row itself), outermost first, hyphen-separated.** Levels with
Multiplicity 1 contribute nothing. Ordinals are always numeric; where the
physical positions have names, record them in `Description` (FTANK-1 left,
FTANK-2 center, FTANK-3 right).

Examples: `HICU-3`, `EMC-1-2`, `BMU-1-7`, `BTMS-2`, `FCC-2`, bare `IRU`. There
is no aircraft-level index (never `EM-4` for “fourth motor on the aircraft”).

### 2. `1_Signals` — one row per logical signal

| Column | What to enter |
|---|---|
| `Signal Id` | Stable unique ID (never reuse) |
| `Same quantity as` | Optional; the other `Signal Id`s observing the *same real-world quantity* (sensor + backup, CON + MON, measured + estimated). Test: one change in the world moves them all at once. Declared on every member, each listing the others |
| `Signal Name` / `Abbreviation` | Human labels |
| `Signal Role` | `Measurement` \| `Command` \| `Request` \| `Computed` \| `Power` |
| `Interfacing Equipment` | Equipment the quantity belongs to (`0_Systems` UniqueId); empty for Computed |
| `Signal Owner` | System that owns the path / computation |
| `Repeated Per` | Extra dimensions not already implied by owner/interfacing equipment (bare UniqueIds like `NAC` or `EM`, **not** `NAC-1`) |
| `Connection Type` | Free-text sensing / connection note |
| `Interface Type` | `Digital` \| `Analog` \| `Discrete` \| `Low Power` \| `High Power` |
| `Unit` / `Functional Minimum` / `Functional Maximum` | Engineering unit and **functional** range of the quantity in service (independent of bus encoding; allocation `Minimum`/`Maximum` hold the wire range) |
| `Computed from` | The `Signal Id`s this value is produced from — computation inputs, or the upstream signal when an owner re-emits an intent it received. Ids only; explain the calculation in `Notes` |
| `Notes` / platform flags | Current-state notes; `On aircraft ?` / `On FND ?` / `On Sim ?` |

#### Linking a signal to another

Two columns, two questions. Apply in order — the first match wins, and if
neither matches there is **no link**:

| Question | Column |
|---|---|
| Are these rows the **same quantity**? | `Same quantity as` |
| Is this value **produced from** other rows? | `Computed from` |

This is an interface document, not an architecture one: record only links that
describe the interface itself. Do **not** record engineering analysis — which
measurement a command is tuned against, companion quantities such as latitude
and longitude, or sibling protection commands. And do not restate what the
database already holds: fields of one message are tied by `Message ID` +
`Label`, a relay keeps one `Signal Id` across its allocations, and a power chain
is visible on the topology map.

#### Signal Role (direction)

| Role | Meaning | Direction | Typical Interface Type |
|---|---|---|---|
| **Measurement** | State acquired from sensing hardware (incl. crew levers / switches) | Interfacing Equipment → Owner | Analog / Discrete / Digital |
| **Command** | Hardwired drive of an effector or safety device | Owner → Interfacing Equipment | Analog / Discrete |
| **Request** | Setpoint / enable / mode asked of another controller over a bus | Owner → Interfacing Equipment | Digital |
| **Computed** | Value derived by the owner | (no physical interface) | Digital |
| **Power** | Electrical supply (one row, nominal energy direction) | Owner (source) → Interfacing Equipment (load) | Low Power (28 V) / High Power (800 V) |

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
| `Bus name` / `Bus description` | Human label and short purpose |
| `Bus Definition` | Exact name of the payload tab for this family (`NAC_CTRL`, …) |
| `Protocol` / `Speed` | Transport and bit rate when known |
| `Topology` | `Unidirectional` or `Shared` for digital buses (drives Bus Topology colors). Analog / Discrete / Low Power / High Power are non-digital kinds |
| `Sender` / `Receiver` | Connected LRU **instances** (naming rule above) |
| platform flags | As needed |

Several bus instances may share one `Bus Definition` so the payload is authored
once. On a shared bus, Sender/Receiver list every node; each allocation names
only its actual producer and intended receivers (usually a subset).

`Message ID`, bit range, encoding and `Refresh period (ms)` on the definition tab
are the inputs for bus load / bandwidth checks: each distinct `Message ID` on a
physical bus instance is one frame type. Where suppliers have not fixed rates,
`Refresh period (ms)` may carry class defaults (working assumptions — see workbook
`README`).

### 4. Bus-definition tabs — allocations on a family

One sheet per `Bus Definition` value (e.g. `NAC_CTRL`, `IRU_TX`). Each row is
one encoded item on that family.

| Column | What to enter |
|---|---|
| `Allocation Id` | Stable row key; **unique workbook-wide**, not only within the tab |
| `Signal Id` | Exactly one `Signal Id` from `1_Signals` (relays: same id on each hop) |
| `Data name` | Human-readable name on this bus |
| `Sender` / `Receiver` | Producer and intended receivers (nodes of every instance of this definition) |
| `Instance dimension` | Extra token when the bus instance alone is not enough (e.g. `PACK-{n}`, `EM-{n}`) |
| `Message ID` | Transport identity: A825/CAN DOC or arbitration id, or A429 label |
| `Label` | Human message / frame name when useful |
| `Start bit` / `Stop bit` | Field bit range (MSB…LSB inclusive) |
| `Encoding` / `Unit` / `Scale` / `Resolution` / `Minimum` / `Maximum` | Wire encoding and engineering mapping; `Minimum`/`Maximum` are the **encoding** range on this bus (often wider than the functional range on `1_Signals`) |
| `Refresh period (ms)` / `Validity` | Refresh period (ms) and how the receiver judges validity |
| `Notes` / platform flags | Current-state notes; applicability flags |

### Cross-cutting rules

- Prefer stable ids (Signal Id, bus ids, Unique Id); rename display names freely.
- Cross-references use ids/UniqueIds, never Excel row numbers or formulas.
- Multiple values in one cell → semicolon-separated.
- Hop identity everywhere is **`Signal Id`**.
- After edits: integrity check, then rebuild Excel for review; promote to
  `ICD_Database.xlsx` only when approved.
