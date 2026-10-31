"""The equity curve counts a position's shares only from when it held them (audit 2026-10-26).

U5-12 fixed ``_build_equity_curve`` between positions: the window starts when every
position was held, because multiplying five years of prices by *today's* share count
fabricates history (a stock bought last month sat in the 2021 drawdown at full size).
IDEA5-LOTES then made a position a list of lots and left the curve as it was:

  * ``Position.purchase_date`` is the **oldest** lot, so the window opened when the
    first lot of the last-opened position was bought; and
  * ``Position.shares`` sums **every** lot.

A position with 10 shares bought in 2022 and 10 more last month therefore entered every
week since 2022 at 20 shares — the same fabrication, now inside one position. Sharpe,
the downside-vol ratio, max drawdown and beta are read off that curve.

The window now opens when every position had reached the size it has today: the date
of the newest lot of any position. Shorter, and short is the honest answer; the
alternative — a time-weighted return that neutralises each purchase — is a bigger design
that this fix does not make.

A second, independent defect on the same line: ``pd.concat(curves, axis=1).sum(axis=1)``
skips NaN, so a week in which one position has no price counted that position as **0**.
That is not rare: measured on live Yahoo data, ``0700.HK`` and ``7203.T`` have no bar for
the current week until their market opens, so any book holding a Hong Kong or Tokyo
position showed the whole value of that position vanishing in the last point of the
curve (and the ``.dropna()`` after the sum never fired: a sum of NaN is 0, not NaN).

References are written from the definition — the value of what was held, week by week —
not from the source. No network: prices are injected.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from config import PORTFOLIO
from portfolio.tracker import Portfolio

_WEEKS = 130


def _start() -> str:
    """Clock-anchored, as in ``test_tracker_curve_oracle``: a fixed date ages out."""
    last = (datetime.now() + timedelta(weeks=1)).date()
    return (last - timedelta(weeks=_WEEKS - 1)).isoformat()


def _prices(start_price: float, drift: float, weeks: int = _WEEKS) -> pd.Series:
    idx = pd.date_range(_start(), periods=weeks, freq="W")
    return pd.Series([start_price * (1 + drift) ** i for i in range(weeks)], index=idx)


def _ago(weeks: int) -> str:
    return (datetime.now() - timedelta(weeks=weeks)).date().isoformat()


@pytest.fixture(autouse=True)
def _no_feed(monkeypatch):
    monkeypatch.setattr("portfolio.tracker.get_info", lambda sym: {})


def _install(monkeypatch, series: dict) -> None:
    monkeypatch.setattr(
        "portfolio.tracker.get_history",
        lambda sym, period="5y", interval="1wk": pd.DataFrame({"close": series[sym]}),
    )
    # A position is valued at its quote, never at its cost (AUDIT-NUMB-2): the last weekly close
    # stands in for it, so the totals and the annualised return of these books exist.
    monkeypatch.setattr(
        "portfolio.tracker.get_info",
        lambda sym: {"currentPrice": float(series[sym].iloc[-1])} if sym in series else {},
    )


def oracle_curve(lots_by_symbol: dict, series: dict) -> pd.Series:
    """Value of what was held, in the weeks when every position already was at today's size.

    ``lots_by_symbol`` maps a symbol to ``[(date_iso, shares), ...]``. A week counts when
    every position has a price in it and it is not before the newest lot of any position.
    """
    opened = max(pd.Timestamp(d) for lots in lots_by_symbol.values() for d, _ in lots)
    weeks = None
    for sym in lots_by_symbol:
        weeks = series[sym].index if weeks is None else weeks.union(series[sym].index)
    values = {}
    for week in weeks:
        if week < opened:
            continue
        if any(pd.isna(series[sym].get(week)) for sym in lots_by_symbol):
            continue
        values[week] = sum(
            sum(shares for _, shares in lots) * series[sym][week]
            for sym, lots in lots_by_symbol.items()
        )
    return pd.Series(values, dtype=float)


class TestSharesAreCountedFromWhenTheyWereHeld:
    def test_a_position_that_doubled_last_month_is_not_double_size_in_old_weeks(self, tmp_path, monkeypatch):
        series = {"KO": _prices(60.0, 0.001), "NVDA": _prices(100.0, 0.010)}
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104))     # the old lot
        p.add_position("NVDA", 50.0, 150.0, purchase_date=_ago(100))
        p.add_position("KO", 100.0, 70.0, purchase_date=_ago(8))       # doubled eight weeks ago

        curve = p._build_equity_curve()
        want = oracle_curve(
            {"KO": [(_ago(104), 100.0), (_ago(8), 100.0)], "NVDA": [(_ago(100), 50.0)]}, series
        )
        assert curve is not None and len(want) > 0
        assert len(curve) == len(want)
        assert list(curve.index) == list(want.index)
        assert curve.values == pytest.approx(want.values)

    def test_the_window_opens_at_the_newest_lot_of_any_position(self, tmp_path, monkeypatch):
        series = {"KO": _prices(60.0, 0.001)}
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104))
        p.add_position("KO", 100.0, 70.0, purchase_date=_ago(8))
        assert p._held_from() == pd.Timestamp(_ago(8))
        assert p._build_equity_curve().index.min() >= pd.Timestamp(_ago(8))

    def test_a_single_lot_book_is_exactly_as_before(self, tmp_path, monkeypatch):
        """Anti-cheat: the window is not shortened for books with one lot per position."""
        series = {"KO": _prices(60.0, 0.001), "NVDA": _prices(100.0, 0.010)}
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104))
        p.add_position("NVDA", 50.0, 150.0, purchase_date=_ago(12))
        assert p._held_from() == pd.Timestamp(_ago(12))
        want = oracle_curve({"KO": [(_ago(104), 100.0)], "NVDA": [(_ago(12), 50.0)]}, series)
        assert p._build_equity_curve().values == pytest.approx(want.values)

    def test_the_measurable_from_date_follows_the_newest_lot(self, tmp_path, monkeypatch):
        series = {"KO": _prices(60.0, 0.001)}
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104))
        p.add_position("KO", 100.0, 70.0, purchase_date=_ago(2))      # too recent: few points
        metrics = p.compute_metrics()
        assert metrics.sharpe_ratio is None
        expected = (pd.Timestamp(_ago(2)) + pd.Timedelta(weeks=PORTFOLIO.min_risk_curve_points - 1)).date()
        assert metrics.risk_measurable_from == expected.isoformat()

    def test_a_lot_without_a_date_has_no_anchor_and_no_curve(self, tmp_path, monkeypatch):
        """No date, no anchor (``_held_from`` is ``None``). The old contract —\"no filter\", the whole
        history — fabricated the very curve this window exists to prevent (AUDIT-RESIDUALES): now there
        is no curve at all. See ``test_tracker_undated_lot_oracle``."""
        series = {"KO": _prices(60.0, 0.001)}
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104))
        p.add_position("KO", 100.0, 70.0, purchase_date="")
        assert p._held_from() is None
        assert p._build_equity_curve() is None


class TestAMissingPriceIsNotAZeroPosition:
    def test_the_current_week_missing_for_one_ticker_does_not_zero_it(self, tmp_path, monkeypatch):
        """0700.HK / 7203.T: no bar yet for the current week, while every US ticker has one."""
        us = _prices(60.0, 0.001)
        hk = _prices(300.0, 0.002).iloc[:-1]                             # the last week is missing
        series = {"KO": us, "0700.HK": hk}
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104))
        p.add_position("0700.HK", 30.0, 280.0, purchase_date=_ago(100))

        curve = p._build_equity_curve()
        want = oracle_curve({"KO": [(_ago(104), 100.0)], "0700.HK": [(_ago(100), 30.0)]}, series)
        assert list(curve.index) == list(want.index)
        assert curve.values == pytest.approx(want.values)
        # The symptom, stated as the thing the user would see: no last-week collapse.
        assert curve.pct_change().dropna().min() > -0.2
        assert curve.index.max() == hk.index.max()

    def test_a_week_missing_in_the_middle_is_skipped_not_zeroed(self, tmp_path, monkeypatch):
        a, b = _prices(60.0, 0.001), _prices(100.0, 0.004)
        b = b.drop(b.index[60])                                           # one interior hole
        series = {"A": a, "B": b}
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("A", 10.0, 55.0, purchase_date=_ago(120))
        p.add_position("B", 10.0, 95.0, purchase_date=_ago(120))
        curve = p._build_equity_curve()
        want = oracle_curve({"A": [(_ago(120), 10.0)], "B": [(_ago(120), 10.0)]}, series)
        assert list(curve.index) == list(want.index)
        assert curve.values == pytest.approx(want.values)

    def test_a_book_with_a_position_that_has_no_history_at_all_still_works(self, tmp_path, monkeypatch):
        """Unchanged: an empty history is skipped (the ``hist.empty`` branch), not an error."""
        monkeypatch.setattr(
            "portfolio.tracker.get_history",
            lambda sym, period="5y", interval="1wk": (
                pd.DataFrame({"close": _prices(60.0, 0.001)}) if sym == "KO" else pd.DataFrame()
            ),
        )
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(200))     # before the history starts
        p.add_position("DEAD", 5.0, 10.0, purchase_date=_ago(200))
        assert len(p._build_equity_curve()) == _WEEKS


class TestMeasurableFromIsNeverInThePast:
    def test_a_short_feed_dates_it_from_the_first_bar_not_from_the_purchase(self, tmp_path, monkeypatch):
        """KO has the whole history; a recent listing has 8 bars. Both were bought long ago.

        The curve is short because the feed is, not because of the purchase, so a date
        counted from the purchase (100 weeks ago + 10) would already be over.
        """
        series = {"KO": _prices(60.0, 0.001), "NEW": _prices(20.0, 0.004, weeks=8)}
        # NEW's 8 bars are the LAST 8 weeks of KO's calendar.
        series["NEW"].index = series["KO"].index[-8:]
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(100))
        p.add_position("NEW", 50.0, 18.0, purchase_date=_ago(100))

        metrics = p.compute_metrics()
        assert metrics.risk_curve_points == 8
        assert metrics.sharpe_ratio is None
        first_bar = series["NEW"].index[0]
        expected = (first_bar + pd.Timedelta(weeks=PORTFOLIO.min_risk_curve_points - 1)).date()
        assert metrics.risk_measurable_from == expected.isoformat()
        assert pd.Timestamp(metrics.risk_measurable_from) > pd.Timestamp(datetime.now().date())

    def test_a_recent_purchase_still_dates_it_from_the_purchase(self, tmp_path, monkeypatch):
        """Anti-cheat: the purchase-bound case keeps the date the page has always said."""
        series = {"KO": _prices(60.0, 0.001)}
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104))
        p.add_position("KO", 50.0, 70.0, purchase_date=_ago(3))
        m = p.compute_metrics()
        expected = (pd.Timestamp(_ago(3)) + pd.Timedelta(weeks=PORTFOLIO.min_risk_curve_points - 1)).date()
        assert m.risk_measurable_from == expected.isoformat()


class TestTheCommandLineSurvivesUnmeasuredRisk:
    def test_portfolio_command_prints_dashes_instead_of_raising(self, tmp_path, monkeypatch, capsys):
        """``:.2f`` on None raised TypeError: a purchase in the last ten weeks broke ``main.py portfolio``."""
        import main

        series = {"KO": _prices(60.0, 0.001)}
        _install(monkeypatch, series)
        p = Portfolio(file_path=tmp_path / "p.json")
        p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104))
        p.add_position("KO", 50.0, 70.0, purchase_date=_ago(2))          # too recent: risk unmeasured
        monkeypatch.setattr(main, "Portfolio", lambda: p)
        main.cmd_portfolio()
        out = capsys.readouterr().out
        assert "Sharpe Ratio : —" in out
        assert "Beta         : —" in out
