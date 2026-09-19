"""Opening a page URL on a cold server must run ``dashboard/app.py`` first.

Streamlit keeps a process-wide flag, ``PagesManager.uses_pages_directory``,
that starts ``True`` when a ``pages/`` folder sits next to the entrypoint.
While it is ``True`` the script runner calls ``_mpa_v1`` instead of the
entrypoint: it builds a menu from the raw folder listing and ``exec``s the
requested page directly. Only the first ``st.navigation`` call flips the flag.
So on a fresh server, ``/Comite`` ran ``15_Comite.py`` without ``app.py`` —
no repo root on ``sys.path`` (``ModuleNotFoundError: dashboard``), no logger,
no session defaults, dev pages exposed.

``AppTest`` resets that flag on every run, so each run is a cold start. Each
case runs in its own interpreter, from a foreign cwd and without the repo root
on ``sys.path``, because pytest's own path would hide the missing bootstrap.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = ROOT / "dashboard" / "views"

# Same user-data isolation as conftest.py, applied inside the child process,
# but on a temp SQLite file: AppTest runs the script on another thread, and a
# ``:memory:`` database is empty on any connection but the one that made it.
_CHILD = textwrap.dedent(
    """
    import json, sys
    root, page, db = sys.argv[1], sys.argv[2], sys.argv[3]
    sys.path.insert(0, root)
    import alerts.store as a
    import analysis.synthetic_backtest as s
    import analysis.track_record as t
    t.track_record_store._engine.dispose()
    t.DB_PATH = db
    t.track_record_store = t.TrackRecordStore()
    s.synthetic_backtest_store._engine.dispose()
    s.DB_PATH = db
    s.synthetic_backtest_store = s.SyntheticBacktestStore()
    a.alert_store._engine.dispose()
    a.DB_PATH = db
    iso = a.AlertStore()
    a.alert_store._engine, a.alert_store._Session = iso._engine, iso._Session
    while root in sys.path:
        sys.path.remove(root)
    assert "dashboard" not in sys.modules
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(root + "/dashboard/app.py", default_timeout=120)
    at.switch_page(page)
    at.run()
    print(json.dumps({
        "exceptions": [e.message for e in at.exception],
        "app_ran": "config_validated" in at.session_state,
    }))
    """
)


@pytest.mark.parametrize("page", ["15_Comite.py", "8_Alertas.py", "3_Portfolio.py", "13_Track_Record.py"])
def test_cold_direct_page_entry_runs_app_first(page, tmp_path):
    rel = (PAGES_DIR / page).relative_to(ROOT / "dashboard").as_posix()
    proc = subprocess.run(
        [sys.executable, "-P", "-c", _CHILD, str(ROOT), rel, str(tmp_path / "test.db")],
        cwd=tmp_path, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["exceptions"] == []
    assert result["app_ran"], f"{page} ran without dashboard/app.py"


def test_no_pages_folder_next_to_entrypoint():
    assert not (ROOT / "dashboard" / "pages").exists(), (
        "dashboard/pages/ makes Streamlit run pages via _mpa_v1, skipping app.py, "
        "until the first st.navigation call — direct URLs break on a cold server. "
        "Page scripts live in dashboard/views/."
    )
