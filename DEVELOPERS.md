# SignalCraft — maintaining the tool

User needs [`README.md`](README.md) instead — nothing here.
Model rules, invariants and silent failure modes:
[`DECISIONS.md`](DECISIONS.md).

## Where things live

| Folder | What is in it |
|---|---|
| `csv/` | The database itself, one file per workbook tab. This is the product. |
| `scripts/` | Command-line tools (export, import, edit, check) |
| `visualizer/` | The Streamlit app |
| `tests/` | Automatic checks that the app still works |

## Before you commit

Double-click **`check.bat`**, or run it from a terminal:

```powershell
.\check.bat
```

It runs three things and stops at the first failure: `ruff` (code mistakes),
`pytest` (the app and the edit engine still work), and the integrity check (the
database is consistent).

There are two test files, kept deliberately small:

| File | What it protects |
|---|---|
| `tests/test_app_smoke.py` | Every page and editor still opens |
| `tests/test_edit_engine.py` | A bad edit is refused and writes nothing; a good one changes only what was asked |

**Keep them small.** They exist to catch the mistakes that are easy to make —
renaming something and missing one use of it, or adding a value in
`scripts/icd_sheets.py` without re-exporting it in `visualizer/data/models.py`.
They are not meant to cover everything. If you add a rule and it would silently
damage the database when broken, add one case to `tests/test_edit_engine.py`.
Otherwise leave them alone: a test nobody understands is worse than no test.

If `ruff` offers to fix things, `uv run ruff check --fix .` applies the safe
ones — but read the result, because it deletes anything it believes is unused.

## Where to change what

| If you want to… | Edit this |
|---|---|
| Add or rename a column | `scripts/icd_sheets.py`, then re-export it in `visualizer/data/models.py` |
| Change an allowed value (Types, Signal Roles, Interface Types, Topologies) | `scripts/icd_sheets.py` — it is the single source of truth |
| Change a validation rule | `scripts/icd_sheets.py` for the shared rules, `scripts/database_integrity_check.py` for the checks |
| Change what the edit forms show | `visualizer/views/edit/` — one file per tab |
| Change how the topology diagram behaves | `visualizer/components/bus_topology.js` (ordinary JavaScript) |
| Change how instance names are built (`EM-1-1`) | `SystemTree` in `scripts/icd_instances.py` — the only place it is worked out |
| Change the diagram's colours | `TOPOLOGY_COLORS` in `scripts/icd_sheets.py` — the whole app reads them from there |
| Add a page | `visualizer/views/`, then list it in `visualizer/app.py` |

## Bus definitions vs bus instances

`10_Databuses` lists **physical links**. Several of them can share one
**Bus Definition** — the payload is then written once, on the tab of that name.
Two links sharing a definition need not be identical: `ADC_TX_1` and `ADC_TX_2`
may carry the same data to different receivers.

So the two columns mean different things, and neither is a copy of the other:

- on `10_Databuses`, **`Bus Definition`** says which tab holds this link's payload;
- on a payload tab, **`definition_tab`** is the tab the row came from — those
  files have no `Bus Definition` column of their own.

Use whichever column belongs to the table you are holding. There is no fallback
between them any more.

**The golden rule:** a sheet name, a column name or an allowed value is written
down **once**, in `scripts/icd_sheets.py`. If you find yourself typing
`"Signal Role"` or `"Component"` into another file, import it instead.

## Offline by design

The database is confidential, so the app must never reach the internet while it
runs. `uv sync` is the only step that needs a connection. Two things keep it
that way — please keep both:

- `.streamlit/config.toml` turns off Streamlit's usage statistics.
- `pyvis` is a dependency **for one file only**: the topology diagram needs the
  `vis-network` JavaScript library, and pyvis ships it inside the package.
  Removing pyvis breaks the diagram.

`uv run pytest` fails if any source file contains an internet address, so this
cannot slip back in unnoticed.

## Command-line tools

| Script | What it does |
|---|---|
| `scripts/excel_to_csv.py` | Export every workbook tab into `csv/` |
| `scripts/csv_to_excel.py` | Build a review workbook from `csv/` |
| `scripts/database_integrity_check.py` | Check ids, references and allocations |
| `scripts/icd_edit.py` | Apply an edit written as JSON |
| `scripts/reorder_sheets.py` | Renumber the CSV files to the reading order (it does **not** reorder the Excel tabs — do that by hand) |

These import shared helpers that are not run directly: `icd_sheets.py` (names
and allowed values), `icd_csv.py` (reading and writing CSV), `icd_instances.py`
(the containment tree), `icd_edit_lib.py` (the edit engine), `icd_paths.py`
(default paths).

## Editing by JSON (`icd_edit.py`)

The visualizer's **Edit data** page builds one of these documents for you, so
you rarely write it by hand. Same engine either way.

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

- **Field left out** → unchanged. **Field set to `""`** → cleared.
- Upsert matches on the sheet's key; leave the key out to get the next free id
  (`SIG-*`, `DBUS-*`). `0_Systems` always needs an explicit `UniqueId`.
- Nothing is written unless every check passes first, so a bad edit changes
  nothing. Add `--dry-run` to see the plan without writing.
- If a multiplicity change would affect bus families, the edit stops and asks
  you to set `options.with_buses` to `true` or `false`.

Ready-made examples: `scripts/examples/edit_*.example.json`.

## The topology diagram

The page is assembled in `visualizer/components/topology_page.py`, but the
interactive behaviour is plain JavaScript in
`visualizer/components/bus_topology.js`. Python decides *what* to draw and hands
it over as one object (`window.SIGNALCRAFT_TOPOLOGY`); the JavaScript decides
how it looks and responds. Edit the `.js` file for anything visual — it is a
normal file your editor can check.
