"""Numeric-environment provenance (audit D5).

A retirement plan is a set of numbers someone makes decisions on. Those numbers
come out of SLSQP (scipy), a block-bootstrap RNG and percentiles (numpy), and
price frames (pandas) — so *which build of those libraries produced them* is
part of the result, not an implementation detail. ``requirements.lock`` pins the
environment going forward; this module records the environment a specific plan
was actually computed in, so an old snapshot can be audited rather than trusted.

Streamlit-free and dependency-free by design: it reads installed versions and
compares strings, nothing more.

Usage::

    from data.env_provenance import numeric_env, env_drift

    snap.lib_versions = numeric_env()
    drift = env_drift(snap.lib_versions)      # {} when the env still matches
"""

from __future__ import annotations

import sys
from typing import Dict

# The libraries whose version can move a reported number. Kept deliberately
# short: adding UI or HTTP packages here would produce drift noise that says
# nothing about whether the maths changed.
NUMERIC_LIBS = ("numpy", "scipy", "pandas")


def _version_of(module_name: str) -> str:
    """Return the installed version of ``module_name``, or "" when unknown.

    Uses importlib.metadata first (does not import the package) and falls back
    to ``__version__`` for packages installed without proper metadata.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return str(version(module_name))
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    try:
        import importlib
        return str(getattr(importlib.import_module(module_name), "__version__", "") or "")
    except Exception:
        return ""


def numeric_env() -> Dict[str, str]:
    """Snapshot the versions that can change a computed figure.

    Returns e.g. ``{"python": "3.12.4", "numpy": "2.2.6", "scipy": "1.17.1",
    "pandas": "3.0.3"}``. Missing entries are omitted rather than stored as
    empty strings, so a later comparison does not report false drift.
    """
    env: Dict[str, str] = {
        "python": ".".join(str(p) for p in sys.version_info[:3]),
    }
    for lib in NUMERIC_LIBS:
        v = _version_of(lib)
        if v:
            env[lib] = v
    return env


def env_drift(saved: Dict[str, str] | None, current: Dict[str, str] | None = None) -> Dict[str, tuple]:
    """Compare a sealed environment against the running one.

    Returns ``{lib: (saved_version, current_version)}`` for every entry that
    changed. An empty dict means the plan's numbers are reproducible here.

    A ``saved`` of None/empty means the plan predates version sealing — that is
    *unknown*, not *equal*, so it returns empty and the caller should treat the
    absence of ``lib_versions`` as its own signal (see
    ``PlanSnapshot.has_sealed_env``).
    """
    if not saved:
        return {}
    now = current if current is not None else numeric_env()
    drift: Dict[str, tuple] = {}
    for key, was in saved.items():
        is_now = now.get(key, "")
        if is_now and str(was) != str(is_now):
            drift[key] = (str(was), str(is_now))
    return drift


def format_drift(drift: Dict[str, tuple]) -> str:
    """Render a drift dict as a short human line ("" when there is no drift)."""
    if not drift:
        return ""
    parts = [f"{lib} {was}→{now}" for lib, (was, now) in sorted(drift.items())]
    return ", ".join(parts)
