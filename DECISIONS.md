# SignalCraft — model rules and invariants

What a change to the database or the tool must respect. Read this before adding
a column, an allowed value, or a view.

- Filling in the database → [`README.md`](README.md)
- Maintaining the tool → [`DEVELOPERS.md`](DEVELOPERS.md)

---

## 1. Scope rule

**This is an interface control document, not an architecture one.** It records
what crosses an interface. It does not record engineering analysis, and it does
not restate what is already derivable.

Before adding any field or link, ask: *could a reader work this out from what is
already stored?* If yes, it does not go in. Things that are already implied:

| Already known from | So do not record |
|---|---|
| same tab + `Message ID` + `Label` | that two rows are fields of one message |
| allocations sharing one `Signal Id` | that a value is relayed onward |
| the topology map | that a power feed chains through several systems |
| `Signal Role` + `Interface Type` | the direction and physical kind of a leg |

Analysis that belongs elsewhere: which measurement a command is tuned against,
why a value is safe, how a control loop is closed.

---

## 2. What is stored, and what is computed

Stored, one file per workbook tab under `csv/`:

| Sheet | One row per | Key |
|---|---|---|
| `0_Systems` | *kind* of equipment, in a containment tree | `UniqueId` |
| `1_Signals` | logical signal | `Signal Id` |
| `10_Databuses` | physical bus instance | `Bus Id` |
| bus-definition tabs | allocation — one data item on one bus definition | `Allocation Id` |

**Instances are never stored.** A row declares `Multiplicity` (count per parent
instance); the instance name is the `UniqueId` plus one ordinal per multiplied
level of its containment chain, outermost first (`EMC-1-2`). `SystemTree` in
`scripts/icd_instances.py` is the only place this is worked out.

**The loader adds two columns to `bus_payload`, computed not stored:**
`definition_tab` (which tab the row came from) and `hop_role`. It also
precomputes four graph frames (`graph_nodes`/`graph_edges` for the full network,
`generic_*` for the collapsed view). Anything derivable belongs here, not in a
sheet.

**A hop is one allocation row**, not a signal. `hop_role` compares the
allocation's `Sender` against the signal's `Signal Owner`: the owner sending it
is `origin` / `computed` / `command` / `request`; anyone else sending it is
`relay`.

---

## 3. Linking one signal to another

Two columns, both holding semicolon-separated `Signal Id`s. Apply the test in
order — first match wins, and if neither matches there is **no link**:

1. Would a single change in the world move these rows **at once**, because they
   observe one and the same quantity? → **`Same quantity as`**
   (a sensor and its backup, a CON and a MON channel, one voltage measured at
   several points, a measured and an estimated value)
2. Otherwise, is this row's value **calculated or forwarded from** other rows?
   → **`Computed from`**
3. Otherwise → nothing.

`Same quantity as` is authored as a mesh — every member lists the others — and
read as an undirected graph, so a half-declared group still resolves whole. The
integrity check warns when a member is named but does not name back.

### Relay is not forward

A **relay** re-broadcasts a value under the *same* `Signal Id`; the extra hops
are allocations and need no link. A **forward** is a *different* signal, because
a different owner re-emits the intent — `HICU` re-issuing a limit it received
from `MBMS`. Only the forward is recorded, in `Computed from`.

---

## 4. Invariants the code depends on

Break one of these and something fails quietly, not loudly.

**An instance name's prefix is its `UniqueId`.** Four places strip trailing
ordinals to recover the system (`_base_acronym`, `base_system_id`, and the
`_INSTANCE_SUFFIX` regex in two components), then look the result up as a
`UniqueId`. Instance ordinals are therefore always numeric.

**A canonical key must normalize to itself.** `normalize_bus_topology` is called
on values that are already keys. Keep every key in `TOPOLOGY_KEYS`; a key that
does not round-trip resolves to `""`, and its links lose their colour and
styling while still drawing.

**`Signal Id` is the only foreign key.** `Bus Id` and `Allocation Id` are primary
keys with no referents. Renaming those is local; renaming a `Signal Id` must go
through `rewrite.ids`, which updates the reference columns.

**Id format is not validated — only uniqueness and references.** But `next_id`
parses `PREFIX-digits` to allocate the next one, so an id outside that shape is
invisible to the allocator and the next auto-allocated id will collide.

**A column name is written once**, in `scripts/icd_sheets.py`, and re-exported
in `visualizer/data/models.py`. `test_models_reexports_every_name_the_app_uses`
enforces the second half.

---

## 5. Silent failure modes

| Mechanism | What you see |
|---|---|
| A guard returns an empty frame when its column is missing (`payloads_for_signal`) | "No allocations" for every signal, no traceback |
| `pd.concat(..., sort=False)` over the bus tabs | a tab left on an old header contributes an all-`NaN` column instead of failing |
| A node created as a function argument, then the edge skipped (`edge(system(a), system(b))` with `a == b`) | a node with no edges; the empty edge frame has no columns, so the figure dies on `groupby` |
| A duplicate primary key | the edit engine refuses **unrelated** edits; the Edit page is unusable until it is fixed |
| Renaming a column but missing a hard-coded literal | the feature reading it silently stops working; ruff cannot see it |

**The Excel ↔ CSV round-trip is one-way at a time.** `csv/` is the working set,
`ICD_Database.xlsx` the source of truth. Running `excel_to_csv.py`, or restoring
`csv/` from an older copy, overwrites uncommitted CSV work. Commit `csv/` before
touching Excel.

---

## 6. Changing the schema

`DEVELOPERS.md` lists which file to edit. The order that avoids a half-migrated
database:

1. **Data first, through `icd_csv`'s `read_sheet` / `write_sheet`** — they
   preserve the BOM, CRLF and quoting, so the diff shows only your change.
   Dry-run, assert every row mapped, then apply.
2. **Constants** in `scripts/icd_sheets.py`, re-exported in
   `visualizer/data/models.py`.
3. **Consumers** — grep for the *literal* as well as the constant; half of every
   rename lives in hard-coded strings.
4. **Validation** — if the new column holds references, add it to the integrity
   check and to `ID_REF_FIELDS` in the edit engine.
5. **Docs** — `Column_Help` (per-column meaning and allowed values) and
   `README.md`.
6. **Rebuild** the review workbook and promote it when approved.

### Verifying it worked

- **Snapshot before, compare after.** When ids change, compare *semantic
  identity* (name, role, interface type, equipment, owner), not ids — ids are
  what changed.
- **Reconstruct a baseline** if the data has already moved: re-add the old
  column synthetically, capture the derived output, diff against the new code.
- **Prove a new guard fires**: break the data in a temp copy and confirm the
  check reports it.
- **Run `check.bat`** — ruff, tests, integrity check.
