# SignalCraft visualizer

Streamlit viewer/editor over the `csv/` working set (not Excel directly).

## Run

From the SignalCraft repo root (after [installing uv and syncing](../README.md#install)):

```powershell
uv run streamlit run visualizer/app.py
```

Sidebar: **Reload database**, **Export to Excel**, **Import Excel → CSV & reload**.

## Pages

| Page | Purpose |
|---|---|
| Bus Topology | Full network or Generic (by `Bus Definition`); layer filters for digital / Analog / Discrete / Power |
| Explorer | Browse `1_Signals`; related allocations via `signal_id` |
| Signal Trace | All hops for one `SIG-*` |
| Edit data | Guided upsert/delete/rewrite (same engine as `icd_edit.py`) — Dry-run then Apply |

Data rules for filling sheets: see the main [`README.md`](../README.md) (“How to fill the database”).
