"""Smoke tests: every visualizer page and editor must render without crashing.

These are deliberately shallow. They do not check that the diagrams are correct
— they check that the app still starts, which is the failure a broken import or
a renamed constant produces. Two real breakages during development are pinned
here so they cannot come back:

* a constant added to ``icd_sheets`` but not re-exported through
  ``visualizer.data.models`` (``test_models_reexports_every_name_the_app_uses``);
* a stale reference left behind after a rename (any of the render tests).

Neither is visible to ruff, so this file is the only thing that catches them.

Run from the repo root::

    uv run pytest
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP = str(PROJECT_ROOT / "visualizer" / "app.py")

PAGES = ["Bus Topology", "Bus Explorer", "Signal Explorer", "Edit data"]
EDITORS = ["System list", "Signals", "Databuses", "Bus definition"]

# Streamlit has to load the CSV working set and build both graphs, so give the
# first script run room on a slow machine.
TIMEOUT = 120


def run_app(**session_state: object) -> AppTest:
    """Run the whole app once with ``session_state`` pre-set, and return it.

    Setting session state before ``run()`` is how a page or a selected row is
    chosen without clicking: the widget keys are the ones used in the source.
    """
    app = AppTest.from_file(APP, default_timeout=TIMEOUT)
    for key, value in session_state.items():
        app.session_state[key] = value
    app.run()
    return app


def assert_no_exception(app: AppTest, context: str) -> None:
    if app.exception:
        pytest.fail(f"{context} raised: {app.exception[0].value}")


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(page: str) -> None:
    assert_no_exception(run_app(nav_page=page), f"Page {page!r}")


@pytest.mark.parametrize("editor", EDITORS)
def test_every_editor_renders(editor: str) -> None:
    app = run_app(nav_page="Edit data", edit_mode=editor)
    assert_no_exception(app, f"Editor {editor!r}")


def test_models_reexports_every_name_the_app_uses() -> None:
    """``visualizer.data.models`` must export everything the app imports from it.

    The module is a facade over ``scripts/icd_sheets.py``. Adding a constant
    there and forgetting to re-export it here breaks the app at import time, and
    no linter reports it because each file is individually valid.
    """
    from visualizer.data import models

    pattern = re.compile(
        r"from visualizer\.data\.models import \(([^)]*)\)"
        r"|from visualizer\.data\.models import ([^\n(]+)"
    )
    missing: dict[str, str] = {}
    for path in PROJECT_ROOT.rglob("*.py"):
        if ".venv" in path.parts or path.name == Path(__file__).name:
            continue
        for groups in pattern.findall(path.read_text(encoding="utf-8")):
            for names in groups:
                for name in names.replace("\n", " ").split(","):
                    name = name.strip()
                    if name and not hasattr(models, name):
                        missing[name] = str(path.relative_to(PROJECT_ROOT))
    assert not missing, f"models.py does not export: {missing}"


def test_signals_editor_shows_every_editable_field() -> None:
    """The Signals editor must cover all of ``1_Signals``, not a subset."""
    from visualizer.views.edit.signals import EDITABLE_FIELDS

    app = run_app(
        nav_page="Edit data",
        edit_mode="Signals",
        edit_sig_selected_id="SIG-001",
        edit_sig_mode="Edit existing",
    )
    assert_no_exception(app, "Signals editor with a row selected")
    assert_fields_editable(app, EDITABLE_FIELDS)


def test_bus_definition_editor_shows_the_transport_fields() -> None:
    """Message id, bit range, encoding and validity must be editable in the app.

    They are what the bus load / bandwidth review needs, and for a long time the
    only way to set them was to go back to Excel.
    """
    app = run_app(
        nav_page="Edit data",
        edit_mode="Bus definition",
        edit_pay_tab="ICM_FCS",
        edit_pay_selected_id="DBUS-ICM-002",
        edit_pay_mode="Edit existing",
    )
    assert_no_exception(app, "Bus definition editor with a row selected")
    expected = {
        "Message ID",
        "Label",
        "start bit",
        "stop bit",
        "scale",
        "resolution",
        "minimum",
        "maximum",
        "validity",
        "On aircraft ?",
        "On FND ?",
        "On Sim ?",
    }
    assert_fields_editable(app, sorted(expected))


def test_aircraft_multiplicity_of_one_is_preserved() -> None:
    """``Multiplicity = 1`` on an Aircraft/Domain row is valid and must survive.

    The editor used to force the field empty for these types, so *any* edit to
    the aircraft row — even a typo fix in its notes — silently cleared the
    stored ``1``. The failure was invisible in the UI: no error was shown, the
    value simply disappeared from the staged document. So this pins the two
    decisions that make it safe, rather than watching for an error banner.
    """
    from visualizer.data.models import system_multiplicity_error
    from visualizer.views.edit.systems import (
        _TOLERATED_NO_INSTANCE_MULTIPLICITY,
    )

    # The shared rule accepts it...
    assert system_multiplicity_error("Aircraft", "1", "") is None
    assert system_multiplicity_error("Domain", "", "") is None
    # ...and the editor leaves it alone instead of rewriting it to "".
    assert "1" in _TOLERATED_NO_INSTANCE_MULTIPLICITY
    # A value left over from a different Type is still corrected.
    assert "3" not in _TOLERATED_NO_INSTANCE_MULTIPLICITY
    assert system_multiplicity_error("Aircraft", "3", "") is not None

    app = run_app(
        nav_page="Edit data",
        edit_mode="System list",
        edit_sys_selected_id="AC",
        edit_sys_mode="Edit existing",
    )
    assert_no_exception(app, "System list on the aircraft row")
    assert [e.value for e in app.error] == []


def test_signal_role_filter_narrows_the_table() -> None:
    everything = run_app(nav_page="Signal Explorer")
    assert_no_exception(everything, "Signal Explorer")
    assert "Signal Role" in {w.label for w in everything.multiselect}

    filtered = run_app(nav_page="Signal Explorer", explorer_role=["Command"])
    assert_no_exception(filtered, "Signal Explorer filtered by role")
    assert _shown_count(filtered) < _shown_count(everything)


# Files whose contents are executed by the app. Documentation is excluded on
# purpose: README links are fine, a URL that runs is not.
RUNTIME_SOURCE = ("*.py", "*.js")


def test_no_source_file_reaches_the_internet() -> None:
    """The ICD database is confidential: nothing may be fetched at runtime.

    Covers the diagram's JavaScript as well as the Python — a CDN link there
    would be just as much of a leak, and just as invisible.
    """
    offenders: dict[str, list[str]] = {}
    for pattern in RUNTIME_SOURCE:
        for path in PROJECT_ROOT.rglob(pattern):
            if ".venv" in path.parts:
                continue
            urls = re.findall(r"https?://\S+", path.read_text(encoding="utf-8"))
            if urls:
                offenders[str(path.relative_to(PROJECT_ROOT))] = urls
    assert not offenders, f"external URL in source: {offenders}"


def assert_fields_editable(app: AppTest, fields: list[str]) -> None:
    """Every column in ``fields`` must have a widget on the page.

    Matched on the start of the label, because some widgets add a hint to the
    column name — "Physical Id (only if shared)" edits ``Physical Id``.
    """
    labels = _widget_labels(app)
    missing = [f for f in fields if not any(lab.startswith(f) for lab in labels)]
    assert not missing, f"no widget for: {missing}"


def _widget_labels(app: AppTest) -> set[str]:
    """Labels of every input widget currently on the page."""
    return {
        widget.label
        for group in (
            app.text_input,
            app.text_area,
            app.selectbox,
            app.multiselect,
        )
        for widget in group
    }


def _shown_count(app: AppTest) -> int:
    """Rows behind the 'N of M signals' caption on Signal Explorer."""
    for caption in app.caption:
        match = re.search(r"(\d+) of \d+ signals", caption.value)
        if match:
            return int(match.group(1))
    raise AssertionError("Signal Explorer did not render its row-count caption")
