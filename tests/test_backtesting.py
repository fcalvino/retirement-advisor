"""Tests for analysis/backtesting.py (audit D4).

The backtest is what tells the user "the scoring model would have beaten SPY".
It had no coverage at all, so nothing checked that the portfolio it builds is
the portfolio it claims to build, or that the gap against the benchmark is
measured over the same window as the return it is subtracted from — the U1-8
defect, whose oracle is ``TestExcessReturnWindow`` below.

Price history is stubbed; the maths is checked in
``tests/test_engine_oracles.py`` against independent references. This file
covers the orchestration: ranking, alignment, excess return, persistence and
the failure paths that must degrade rather than crash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

import analysis.backtesting as bt_mod
from analysis.backtesting import BacktestEngine, BacktestResult, TickerPerformance


@dataclass
class _Scored:
    """Duck-typed stand-in for a FundamentalResult."""
    symbol: str
    adjusted_score: float


def _price_frame(start: float, annual_rate: float, n_bars: int = 320) -> pd.DataFrame:
    """Weekly closes growing at a steady annual rate, ending today."""
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n_bars, freq="W")
    weekly = (1.0 + annual_rate) ** (1.0 / 52.0)
    return pd.DataFrame({"close": start * weekly ** np.arange(n_bars)}, index=idx)


RATES = {"SPY": 0.08, "AAA": 0.15, "BBB": 0.10, "CCC": 0.02}


@pytest.fixture
def stub_history(monkeypatch):
    def _get_history(symbol, period="5y", interval="1wk"):
        if symbol not in RATES:
            return pd.DataFrame()
        return _price_frame(100.0, RATES[symbol])
    monkeypatch.setattr(bt_mod, "get_history", _get_history)
    return _get_history


# ------------------------------------------------------------------ #
#  Ranking & portfolio construction                                    #
# ------------------------------------------------------------------ #

class TestRanking:
    def test_top_n_is_selected_by_score(self, stub_history):
        scored = [_Scored("CCC", 40.0), _Scored("AAA", 90.0), _Scored("BBB", 70.0)]
        result = BacktestEngine().run(scored, period_years=5, top_n=2)
        picked = [n for n in result.notes if n.startswith("Portfolio:")][0]
        assert "AAA" in picked and "BBB" in picked
        assert "CCC" not in picked

    def test_unscored_tickers_are_excluded(self, stub_history):
        scored = [_Scored("AAA", 90.0), _Scored("BBB", 0.0)]
        result = BacktestEngine().run(scored, period_years=5, top_n=5)
        picked = [n for n in result.notes if n.startswith("Portfolio:")][0]
        assert "BBB" not in picked

    def test_universe_size_counts_everything_supplied(self, stub_history):
        scored = [_Scored("AAA", 90.0), _Scored("BBB", 70.0), _Scored("CCC", 40.0)]
        assert BacktestEngine().run(scored, top_n=1).universe_size == 3

    def test_tickers_without_price_history_are_noted_and_skipped(self, stub_history):
        scored = [_Scored("AAA", 90.0), _Scored("GHOST", 80.0)]
        result = BacktestEngine().run(scored, top_n=2)
        assert any("GHOST" in n for n in result.notes)
        assert result.portfolio_cagr_pct != 0.0     # still ran on AAA


# ------------------------------------------------------------------ #
#  Metrics reported to the user                                        #
# ------------------------------------------------------------------ #

class TestReportedMetrics:
    def test_single_holding_reproduces_its_own_growth_rate(self, stub_history):
        """A one-stock portfolio must report that stock's actual CAGR."""
        result = BacktestEngine().run([_Scored("AAA", 90.0)], period_years=5, top_n=1)
        assert result.portfolio_cagr_pct == pytest.approx(15.0, abs=0.3)

    def test_benchmark_cagr_matches_the_benchmark(self, stub_history):
        result = BacktestEngine().run([_Scored("AAA", 90.0)], period_years=5, top_n=1)
        assert result.benchmark_cagr_pct == pytest.approx(8.0, abs=0.3)

    def test_excess_return_is_portfolio_minus_benchmark(self, stub_history):
        result = BacktestEngine().run([_Scored("AAA", 90.0)], period_years=5, top_n=1)
        assert result.excess_return_pct == pytest.approx(
            round(result.portfolio_cagr_pct - result.benchmark_cagr_pct, 2)
        )

    def test_a_laggard_produces_a_negative_excess_return(self, stub_history):
        result = BacktestEngine().run([_Scored("CCC", 90.0)], period_years=5, top_n=1)
        assert result.excess_return_pct < 0

    def test_curves_are_normalised_to_100(self, stub_history):
        result = BacktestEngine().run([_Scored("AAA", 90.0)], top_n=1)
        assert next(iter(result.portfolio_curve.values())) == pytest.approx(100.0)
        assert next(iter(result.benchmark_curve.values())) == pytest.approx(100.0)

    def test_monotonic_series_never_draws_down(self, stub_history):
        result = BacktestEngine().run([_Scored("AAA", 90.0)], top_n=1)
        assert result.portfolio_max_drawdown_pct == pytest.approx(0.0, abs=1e-6)
        assert all(v <= 1e-6 for v in result.drawdown_curve.values())

    def test_per_ticker_breakdown_covers_the_whole_universe(self, stub_history):
        scored = [_Scored("AAA", 90.0), _Scored("BBB", 70.0), _Scored("CCC", 40.0)]
        result = BacktestEngine().run(scored, top_n=1)
        assert {t.symbol for t in result.ticker_results} == {"AAA", "BBB", "CCC"}
        assert len(result.score_vs_return) == 3

    def test_lookahead_bias_is_always_disclosed(self, stub_history):
        """The scores use current financials — the caveat must never be dropped."""
        result = BacktestEngine().run([_Scored("AAA", 90.0)], top_n=1)
        assert any("lookahead" in n.lower() for n in result.notes)


# ------------------------------------------------------------------ #
#  Rebalancing plumbing                                                #
# ------------------------------------------------------------------ #

class TestRebalanceDates:
    IDX = pd.date_range("2020-01-05", periods=52 * 5, freq="W")

    def test_buy_and_hold_has_no_rebalance_dates(self):
        assert BacktestEngine()._rebalance_dates(self.IDX, "buy_and_hold") == set()

    def test_unknown_frequency_is_treated_as_no_rebalancing(self):
        assert BacktestEngine()._rebalance_dates(self.IDX, "fortnightly") == set()

    @pytest.mark.parametrize("freq,expected", [("annual", 5), ("quarterly", 20), ("monthly", 60)])
    def test_cadence_produces_the_expected_number_of_dates(self, freq, expected):
        dates = BacktestEngine()._rebalance_dates(self.IDX, freq)
        assert abs(len(dates) - expected) <= 1        # calendar-edge tolerance

    def test_dates_land_on_real_bars(self):
        dates = BacktestEngine()._rebalance_dates(self.IDX, "annual")
        assert all(d in self.IDX for d in dates)

    @pytest.mark.parametrize("freq", ["buy_and_hold", "annual", "quarterly", "monthly"])
    def test_every_frequency_produces_a_usable_curve(self, stub_history, freq):
        result = BacktestEngine().run(
            [_Scored("AAA", 90.0), _Scored("BBB", 70.0)], top_n=2, rebalance_freq=freq
        )
        assert result.rebalance_freq == freq
        assert len(result.portfolio_curve) > 10


# ------------------------------------------------------------------ #
#  Failure paths                                                       #
# ------------------------------------------------------------------ #

class TestDegradesGracefully:
    def test_missing_benchmark_reports_an_error_note(self, monkeypatch):
        monkeypatch.setattr(bt_mod, "get_history", lambda *a, **k: pd.DataFrame())
        result = BacktestEngine().run([_Scored("AAA", 90.0)], top_n=1)
        assert any("ERROR" in n for n in result.notes)
        assert result.portfolio_cagr_pct == 0.0

    def test_no_portfolio_price_data_reports_an_error_note(self, monkeypatch):
        def only_spy(symbol, **k):
            return _price_frame(100.0, 0.08) if symbol == "SPY" else pd.DataFrame()
        monkeypatch.setattr(bt_mod, "get_history", only_spy)
        result = BacktestEngine().run([_Scored("GHOST", 90.0)], top_n=1)
        assert any("ERROR" in n for n in result.notes)

    def test_empty_universe_does_not_raise(self, stub_history):
        result = BacktestEngine().run([], top_n=5)
        assert result.universe_size == 0


# ------------------------------------------------------------------ #
#  Persistence                                                        #
# ------------------------------------------------------------------ #

class TestPersistence:
    def test_save_then_load_roundtrips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bt_mod, "RESULTS_DIR", tmp_path)
        result = BacktestResult(
            run_date="2026-08-14T10:00:00", period_years=5,
            start_date="2021-08-14", end_date="2026-08-14",
            benchmark="SPY", top_n=2, universe_size=10,
            portfolio_cagr_pct=12.5, excess_return_pct=4.5,
        )
        result.ticker_results = [
            TickerPerformance("AAA", 90.0, 15.0, 1.1, 1.4, -12.0, 18.0, 55.0, 110.0, 7.0)
        ]
        path = BacktestEngine().save(result, filename="rt.json")
        loaded = BacktestEngine.load(path)

        assert loaded.portfolio_cagr_pct == 12.5
        assert loaded.excess_return_pct == 4.5
        assert loaded.ticker_results[0].symbol == "AAA"
        assert loaded.ticker_results[0].cagr_pct == 15.0

    def test_list_saved_returns_newest_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bt_mod, "RESULTS_DIR", tmp_path)
        for name in ("backtest_a.json", "backtest_b.json", "ignore_me.json"):
            (tmp_path / name).write_text("{}")
        found = [p.name for p in BacktestEngine.list_saved()]
        assert found == ["backtest_b.json", "backtest_a.json"]


# ------------------------------------------------------------------ #
#  U1-8: the two legs of the excess return share one window           #
# ------------------------------------------------------------------ #

#: Bars of the stub that the late-listing ticker exists for (~2 years).
TAIL_BARS = 105
#: Annualised rate the benchmark runs at inside those last bars.
TAIL_RATE = 0.20


def _piecewise_bench(n_bars: int = 320, tail_bars: int = TAIL_BARS) -> pd.DataFrame:
    """Benchmark that is flat for years and then rallies at ``TAIL_RATE``.

    The point of the shape: the benchmark's CAGR over the whole window and over
    its last two years are different numbers, so a comparison that mixes the two
    windows cannot accidentally come out right.
    """
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n_bars, freq="W")
    tail_weekly = (1.0 + TAIL_RATE) ** (1.0 / 52.0)
    values = [100.0]
    for i in range(1, n_bars):
        values.append(values[-1] * (tail_weekly if i >= n_bars - tail_bars else 1.0))
    return pd.DataFrame({"close": values}, index=idx)


def oracle_cagr_between(prices: pd.Series, start, end) -> float:
    """CAGR of ``prices`` between two dates, straight from the definition.

    Written from "the rate that compounds the first value into the last over the
    elapsed time", not from ``BacktestEngine._metrics`` — the engine is what is
    on trial here.
    """
    window = prices[(prices.index >= start) & (prices.index <= end)]
    years = (len(window) - 1) / 52.0
    return ((window.iloc[-1] / window.iloc[0]) ** (1.0 / years) - 1.0) * 100.0


@pytest.fixture
def stub_uneven_history(monkeypatch):
    """A benchmark and a full-history holding, plus two late-listing tickers.

    ``SHORT`` runs at exactly the benchmark's tail rate, so its honest excess
    return is zero; ``FAST`` runs 10 points above it.
    """
    frames = {
        "BENCH": _piecewise_bench(),
        "LONG":  _price_frame(100.0, 0.10),
        "SHORT": _price_frame(100.0, TAIL_RATE, n_bars=TAIL_BARS),
        "FAST":  _price_frame(100.0, TAIL_RATE + 0.10, n_bars=TAIL_BARS),
    }

    def _get_history(symbol, period="5y", interval="1wk"):
        return frames.get(symbol, pd.DataFrame()).copy()

    monkeypatch.setattr(bt_mod, "get_history", _get_history)
    return frames


class TestExcessReturnWindow:
    """U1-8: a ticker's excess return is measured against the benchmark *it* saw.

    The per-ticker row used to subtract the benchmark CAGR computed over the
    *portfolio's* overlap, so a ticker listed two years ago was scored against a
    five-year benchmark rate.
    """

    @staticmethod
    def _run(stub):
        return BacktestEngine().run(
            [_Scored("LONG", 90.0), _Scored("SHORT", 50.0), _Scored("FAST", 40.0)],
            period_years=5, top_n=1, benchmark="BENCH",
        )

    @staticmethod
    def _row(result, symbol):
        return next(t for t in result.ticker_results if t.symbol == symbol)

    def test_the_two_windows_really_do_disagree(self, stub_uneven_history):
        """Guard on the fixture: without this gap the test proves nothing."""
        result = self._run(stub_uneven_history)
        short_cagr = self._row(result, "SHORT").cagr_pct
        assert short_cagr == pytest.approx(TAIL_RATE * 100, abs=0.3)
        assert abs(result.benchmark_cagr_pct - short_cagr) > 5.0

    def test_a_late_listing_matching_the_benchmark_shows_no_excess(
        self, stub_uneven_history
    ):
        result = self._run(stub_uneven_history)
        assert self._row(result, "SHORT").excess_return_pct == pytest.approx(0.0, abs=0.5)

    def test_a_late_listing_beating_the_benchmark_keeps_only_its_own_edge(
        self, stub_uneven_history
    ):
        result = self._run(stub_uneven_history)
        row = self._row(result, "FAST")
        assert row.excess_return_pct == pytest.approx(10.0, abs=0.6)

    def test_excess_matches_a_benchmark_cagr_derived_over_the_same_dates(
        self, stub_uneven_history
    ):
        """The oracle: recompute the benchmark leg from the definition."""
        result = self._run(stub_uneven_history)
        bench = stub_uneven_history["BENCH"]["close"]

        # The engine also clips everything at ``start_date``; the shared window
        # is the latest of the three starts.
        cutoff = pd.Timestamp(result.start_date)
        for symbol in ("LONG", "SHORT", "FAST"):
            row = self._row(result, symbol)
            own = stub_uneven_history[symbol]["close"]
            start = max(own.index[0], bench.index[0], cutoff)
            expected = row.cagr_pct - oracle_cagr_between(bench, start, own.index[-1])
            assert row.excess_return_pct == pytest.approx(expected, abs=0.3), symbol

    def test_a_full_history_holding_is_unaffected_by_the_fix(self, stub_uneven_history):
        """The window fix must not move a ticker that already shared the window."""
        result = self._run(stub_uneven_history)
        row = self._row(result, "LONG")
        assert row.excess_return_pct == pytest.approx(
            round(row.cagr_pct - result.benchmark_cagr_pct, 2), abs=0.3
        )


# ------------------------------------------------------------------ #
#  U1-8 / U1-9: results saved under the old field names still load    #
# ------------------------------------------------------------------ #

class TestLegacyFieldNames:
    def test_a_pre_rename_backtest_loads_under_the_new_names(self, tmp_path, monkeypatch):
        """``data/db/backtests/`` holds runs saved before the rename."""
        monkeypatch.setattr(bt_mod, "RESULTS_DIR", tmp_path)
        legacy = {
            "run_date": "2026-05-24T13:18:05", "period_years": 5,
            "start_date": "2021-05-24", "end_date": "2026-05-24",
            "benchmark": "SPY", "top_n": 10, "universe_size": 78,
            "portfolio_cagr_pct": 18.0, "alpha_pct": 4.5, "portfolio_sortino": 1.91,
            "ticker_results": [{
                "symbol": "AAA", "score": 90.0, "cagr_pct": 15.0, "sharpe": 1.1,
                "sortino": 1.4, "max_drawdown_pct": -12.0, "volatility_pct": 18.0,
                "win_rate_pct": 55.0, "total_return_pct": 110.0, "alpha_pct": 7.0,
            }],
        }
        path = tmp_path / "backtest_legacy.json"
        path.write_text(json.dumps(legacy))

        loaded = BacktestEngine.load(path)

        assert loaded.excess_return_pct == 4.5
        assert loaded.portfolio_downside_vol_ratio == 1.91
        assert loaded.ticker_results[0].excess_return_pct == 7.0
        assert loaded.ticker_results[0].downside_vol_ratio == 1.4

    def test_migration_never_moves_a_number(self, tmp_path, monkeypatch):
        """Renaming a historical run must not restate what it reported."""
        monkeypatch.setattr(bt_mod, "RESULTS_DIR", tmp_path)
        path = tmp_path / "backtest_x.json"
        path.write_text(json.dumps({
            "run_date": "2026-05-24T13:18:05", "period_years": 5,
            "start_date": "2021-05-24", "end_date": "2026-05-24",
            "benchmark": "SPY", "top_n": 10, "universe_size": 78,
            "alpha_pct": -3.25,
        }))
        assert BacktestEngine.load(path).excess_return_pct == -3.25

    def test_the_shipped_saved_backtest_still_loads(self):
        """The real file in the repo, not a fixture."""
        saved = sorted(bt_mod.RESULTS_DIR.glob("backtest_*.json"))
        if not saved:
            pytest.skip("no saved backtest in data/db/backtests/")
        result = BacktestEngine.load(saved[0])
        assert isinstance(result.excess_return_pct, float)
        assert isinstance(result.portfolio_downside_vol_ratio, float)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
