"""SignalCraft visualizer — Streamlit entrypoint.

Run from the SignalCraft repo root:

    uv sync
    uv run streamlit run visualizer/app.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from visualizer.data.loader import csv_mtime_key, load_icd  # noqa: E402
from visualizer.data.workbook_io import (  # noqa: E402
    IncompatibleWorkbookError,
    export_csv_to_excel,
    import_excel_to_csv,
)
from visualizer.views import (  # noqa: E402
    bus_explorer,
    bus_topology,
    edit_data,
    explorer,
)

st.set_page_config(
    page_title="SignalCraft",
    page_icon="📡",
    layout="wide",
)

_EXPORT_BYTES_KEY = "sidebar_export_bytes"
_EXPORT_NAME_KEY = "sidebar_export_download_name"
_BANNERS = (
    _PROJECT_ROOT / "SignalCraft_sidebar.jpg",  # 600px, ~85x lighter than the source
    _PROJECT_ROOT / "SignalCraft.png",
)


@st.cache_data(show_spinner="Loading ICD CSVs…")
def _cached_load(mtime_key: str):
    return load_icd(mtime_key)


def _suggested_export_name(raw: str) -> str:
    name = (raw or "").strip() or "ICD_Database_export.xlsx"
    name = Path(name).name  # no path traversal via text field
    if Path(name).suffix.lower() not in {".xlsx", ".xlsm"}:
        name = f"{name}.xlsx"
    return name


def _render_sidebar_io() -> None:
    st.sidebar.divider()
    if st.sidebar.button(
        "Reload database",
        key="sidebar_reload_db",
        help="Clear the CSV cache and reload from csv/.",
        use_container_width=True,
    ):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.caption(
        "Excel export uses your browser’s save dialog. "
        "Import overwrites the working `csv/` set."
    )

    export_name = st.sidebar.text_input(
        "Export file name",
        value="ICD_Database_export.xlsx",
        key="sidebar_export_filename",
        help="Name offered to the browser when you download the rebuilt workbook.",
    )
    if st.sidebar.button(
        "Export to Excel",
        key="sidebar_export_excel",
        help="Rebuild a workbook from csv/ and offer it for download.",
        use_container_width=True,
    ):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / _suggested_export_name(export_name)
                export_csv_to_excel(out)
                st.session_state[_EXPORT_BYTES_KEY] = out.read_bytes()
                st.session_state[_EXPORT_NAME_KEY] = out.name
            st.sidebar.success("Workbook ready — use Download below.")
        except Exception as exc:  # noqa: BLE001 — surface rebuild errors in UI
            st.sidebar.error(f"Export failed: {exc}")

    if st.session_state.get(_EXPORT_BYTES_KEY):
        st.sidebar.download_button(
            "Download Excel file",
            data=st.session_state[_EXPORT_BYTES_KEY],
            file_name=st.session_state.get(
                _EXPORT_NAME_KEY, "ICD_Database_export.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            key="sidebar_download_excel",
            use_container_width=True,
        )

    uploaded = st.sidebar.file_uploader(
        "Load Excel file",
        type=["xlsx", "xlsm"],
        key="sidebar_import_excel",
        help="Replace csv/ from this workbook, then reload the visualizer.",
    )
    if st.sidebar.button(
        "Import Excel → CSV & reload",
        key="sidebar_import_apply",
        help="Overwrite csv/ from the uploaded workbook and clear the cache.",
        use_container_width=True,
        disabled=uploaded is None,
    ):
        try:
            assert uploaded is not None
            import_excel_to_csv(
                uploaded.getvalue(),
                source_name=uploaded.name or "upload.xlsx",
            )
            st.cache_data.clear()
            st.session_state.pop(_EXPORT_BYTES_KEY, None)
            st.session_state.pop(_EXPORT_NAME_KEY, None)
            st.sidebar.success("CSV updated — reloading…")
            st.rerun()
        except IncompatibleWorkbookError as exc:
            st.sidebar.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Import failed: {exc}")


def main() -> None:
    banner = next((path for path in _BANNERS if path.is_file()), None)
    if banner:
        st.sidebar.image(str(banner), width="stretch")
    else:  # keep the ribbon labelled if no banner ships with the checkout
        st.sidebar.title("SignalCraft")

    key = csv_mtime_key()
    bundle = _cached_load(key)

    st.sidebar.metric("Systems", len(bundle.systems))
    st.sidebar.metric("Signals", len(bundle.signals))
    st.sidebar.metric("Buses", len(bundle.buses))
    st.sidebar.metric("Bus allocations", len(bundle.bus_payload))

    page = st.sidebar.radio(
        "Page",
        [
            "Bus Topology",
            "Bus Explorer",
            "Signal Explorer",
            "Edit data",
        ],
        index=0,
        key="nav_page",
    )

    _render_sidebar_io()

    if page == "Bus Topology":
        bus_topology.render(bundle)
    elif page == "Bus Explorer":
        bus_explorer.render(bundle)
    elif page == "Signal Explorer":
        explorer.render(bundle)
    else:
        edit_data.render(bundle)


main()
