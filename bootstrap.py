"""
Single project-root ``sys.path`` bootstrap.

Call ``ensure_project_root()`` at process entry points (CLI, Streamlit app,
scripts) before importing project packages (``analysis``, ``config``, …).

Streamlit multipage entry is ``streamlit run dashboard/app.py`` (or ``run.sh``),
which bootstraps the root before pages are loaded via ``st.Page``. Pages
themselves should not re-insert into ``sys.path``.

Hermes / OAuth vendor paths (``hermes_path``) are unrelated and stay local to
the AI provider code.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def ensure_project_root() -> Path:
    """Insert the repository root on ``sys.path`` once; return the root Path."""
    root = str(_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return _ROOT


# Allow ``import bootstrap`` as a side-effect bootstrap when convenient.
ensure_project_root()
