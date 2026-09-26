"""TR-STALE-PRICE — el scorer del track record no pone un precio viejo como si fuera de hoy.

``track_record_scorer._price_on_or_before`` devolvía el último cierre ≤ fecha
**sin importar su antigüedad**. Un ticker que dejó de cotizar (o una caché que
quedó cortada) se "cotizaba" en el horizonte con un cierre de meses antes, y la
fila se persistía como un outcome medido que no lo es. PIT-1 ya resolvió lo
mismo para el backtesting sintético con ``price_near``; este oráculo exige que
el scorer en vivo use la misma guarda (``TRACK_RECORD.max_price_staleness_days``).

El oráculo se escribe desde la definición: el precio de una fecha es el cierre
de ese día o del último día hábil anterior **a lo sumo** ``max_price_staleness_days``
días calendario antes; nunca uno posterior; si no hay tal cierre, ``None`` y la
fila queda ``skipped`` (se reintenta, no se persiste nada inventado).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

import analysis.track_record_scorer as scorer
from config import TRACK_RECORD

STALE = TRACK_RECORD.max_price_staleness_days


def _daily(start: str, end: str, value: float = 100.0) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="D")
    index.name = "Date"
    return pd.DataFrame({"close": [value + i for i in range(len(index))]}, index=index)


@pytest.fixture
def history(monkeypatch):
    """Inyecta la historia que ``get_history`` devolvería, sin red."""
    frames: dict = {}

    def fake_get_history(symbol, period="max", interval="1d"):
        return frames.get(symbol, pd.DataFrame())

    import data.fetcher

    monkeypatch.setattr(data.fetcher, "get_history", fake_get_history)
    return frames


def test_the_guard_lives_in_track_record_config():
    assert isinstance(STALE, int) and STALE > 0


def test_a_close_older_than_the_guard_is_not_a_price(history):
    history["X"] = _daily("2026-01-01", "2026-03-01")
    when = datetime(2026, 3, 1) + timedelta(days=STALE + 1)
    assert scorer._price_on_or_before("X", when) is None


def test_a_close_exactly_at_the_guard_still_counts(history):
    history["X"] = _daily("2026-01-01", "2026-03-01")
    last = float(history["X"]["close"].iloc[-1])
    when = datetime(2026, 3, 1) + timedelta(days=STALE)
    assert scorer._price_on_or_before("X", when) == pytest.approx(last)


def test_never_a_close_from_after_the_date(history):
    history["X"] = _daily("2026-01-01", "2026-03-01")
    expected = float(history["X"].loc["2026-02-10", "close"])
    assert scorer._price_on_or_before("X", datetime(2026, 2, 10, 15, 30)) == pytest.approx(expected)


def test_no_history_is_no_price(history):
    assert scorer._price_on_or_before("NADA", datetime(2026, 2, 10)) is None


def test_a_stale_horizon_price_leaves_the_row_unscored():
    """End-to-end: la fila con cierre viejo al horizonte queda ``skipped``, nada se guarda."""
    created = datetime(2026, 1, 5)
    rec = SimpleNamespace(id=1, symbol="GONE", action="BUY", created_at=created, price_at_rec=None)
    saved = []

    class Store:
        def get_pending_scoring(self, horizon, now=None):
            return [rec] if horizon == 30 else []

        def save_outcome(self, **kw):
            saved.append(kw)

    frames = {
        "GONE": _daily("2025-12-01", "2026-01-10"),   # dejó de cotizar el 10/01
        TRACK_RECORD.benchmark: _daily("2025-12-01", "2026-06-01"),
    }

    def lookup(symbol, when):
        from analysis.price_lookup import price_near

        return price_near(frames.get(symbol, pd.DataFrame()), when.date(), STALE)

    out = scorer.score_due_recommendations(Store(), now=datetime(2026, 6, 1), price_lookup=lookup)
    assert out == {"scored": 0, "partial": 0, "skipped": 1}
    assert saved == []
