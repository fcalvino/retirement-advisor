"""The tracker's curve, and the return it does not compute (backlog U5-12).

Two defects on the module that judges the user's own portfolio.

**It promised an IRR it never had.** ``tracker.py``'s header advertised
"annualized return (IRR/XIRR)". Measured, the string ``irr`` appears exactly once
in the module — in that line. What is computed is
``(total_value / total_cost) ** (1 / years) - 1``, with ``years`` taken from the
**earliest** purchase across every position. An IRR weights each cash flow by its
own timing; this weights none of them. Buy $1 000 five years ago and $99 000
yesterday and the $99 000 is credited with five years of compounding.

Implementing a real IRR is X-02, explicitly out of scope. The fix is therefore the
label, in the pattern U1-1/U1-5/U1-6/U1-9 already set for this codebase.

**The equity curve gave every position five years of history at today's size.**
``_build_equity_curve`` multiplied five years of prices by ``pos.shares`` — the
share count as of *now* — for every holding, whatever its purchase date. A stock
bought last month appeared in the portfolio's 2021 drawdown at full size. Four
metrics are read off that curve: the Sharpe ratio, the downside-vol ratio, the max
drawdown and the beta.

On a deliberately ordinary two-position book — KO held throughout, NVDA bought
three months ago — the fabricated history reports Sharpe **1.04** where the real
shared window gives **1.91**, and a max drawdown of **−20.3 %** against **−3.2 %**
that the portfolio never lived through.

The curve now starts where every position is actually held. That is shorter, and
short is the honest answer: with less than the required window the metrics are
suppressed rather than estimated. Zeroing a position before its purchase instead
would put a step change into the series, and a purchase is not a return — it
would show up as one enormous week of volatility.

No network: prices are injected.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from portfolio.tracker import Portfolio


def _weekly(start: str, n: int, start_price: float, weekly_drift: float) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="W")
    prices = [start_price * (1 + weekly_drift) ** i for i in range(n)]
    return pd.DataFrame({"close": prices}, index=idx)


class _Book:
    """A portfolio with injected prices and no disk or network."""

    def __init__(self, tmp_path, positions, histories):
        self.p = Portfolio(file_path=tmp_path / "portfolio.json")
        for sym, (shares, cost, when) in positions.items():
            self.p.add_position(sym, shares, cost, purchase_date=when)
        self.histories = histories


@pytest.fixture
def book(tmp_path, monkeypatch):
    """KO held for two years; NVDA bought twelve weeks ago."""
    old = (datetime.now() - timedelta(weeks=104)).date().isoformat()
    recent = (datetime.now() - timedelta(weeks=12)).date().isoformat()
    histories = {
        "KO": _weekly("2024-01-07", 130, 60.0, 0.001),
        "NVDA": _weekly("2024-01-07", 130, 100.0, 0.010),
    }
    monkeypatch.setattr(
        "portfolio.tracker.get_history",
        lambda sym, period="5y", interval="1wk": histories[sym],
    )
    b = _Book(tmp_path, {"KO": (100.0, 55.0, old), "NVDA": (50.0, 150.0, recent)}, histories)
    return b.p


class TestTheCurveOnlyCoversWhatWasHeld:
    def test_it_starts_where_every_position_is_held(self, book):
        curve = book._build_equity_curve()
        assert curve is not None
        latest_purchase = max(
            datetime.fromisoformat(p.purchase_date) for p in book.positions.values()
        )
        assert curve.index.min() >= pd.Timestamp(latest_purchase)

    def test_a_recent_buy_does_not_appear_in_an_old_drawdown(self, book):
        """The defect, stated as a length: five years of a twelve-week holding."""
        curve = book._build_equity_curve()
        assert len(curve) < 30

    def test_the_curve_has_no_step_from_a_purchase(self, book):
        """A purchase is not a return, so it must not show up as one.

        Zeroing a position before its purchase date would be the other way to
        keep the shares honest, and it puts one enormous week into the series.
        """
        curve = book._build_equity_curve()
        weekly = curve.pct_change().dropna().abs()
        assert weekly.max() < 0.5

    def test_a_single_position_keeps_its_whole_history(self, tmp_path, monkeypatch):
        """Anti-cheat: the window is not shortened for its own sake."""
        hist = _weekly("2024-01-07", 130, 60.0, 0.001)
        monkeypatch.setattr(
            "portfolio.tracker.get_history",
            lambda sym, period="5y", interval="1wk": hist,
        )
        old = (datetime.now() - timedelta(weeks=200)).date().isoformat()
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=old)
        assert len(p._build_equity_curve()) == len(hist)

    def test_too_little_shared_history_reports_nothing(self, tmp_path, monkeypatch):
        """Short is an honest answer; an estimate from fabricated history is not."""
        hist = _weekly("2024-01-07", 130, 60.0, 0.001)
        monkeypatch.setattr(
            "portfolio.tracker.get_history",
            lambda sym, period="5y", interval="1wk": hist,
        )
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0,
                       purchase_date=(datetime.now() - timedelta(weeks=200)).date().isoformat())
        p.add_position("NVDA", 10.0, 100.0,
                       purchase_date=(datetime.now() - timedelta(days=3)).date().isoformat())

        metrics = p.compute_metrics()
        assert metrics.sharpe_ratio == 0
        assert metrics.max_drawdown_pct == 0


class TestTheReturnIsNamedForWhatItIs:
    def test_the_module_no_longer_advertises_an_irr(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "portfolio" /
               "tracker.py").read_text(encoding="utf-8")
        header = src.split('"""')[1]
        assert "IRR" not in header and "XIRR" not in header

    def test_the_field_says_it_ignores_when_the_money_arrived(self):
        from portfolio.tracker import ANNUALIZED_RETURN_CAVEAT

        low = ANNUALIZED_RETURN_CAVEAT.lower()
        assert "irr" in low
        assert "primera compra" in low or "aporte" in low

    def test_no_surface_calls_it_an_irr(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        page = (root / "dashboard" / "pages" / "3_Portfolio.py").read_text(encoding="utf-8")
        assert "IRR" not in page
        assert "ANNUALIZED_RETURN_CAVEAT" in page


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
