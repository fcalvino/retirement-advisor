"""Oracle tests for Backtesting over tickers quoted in another currency (#154, PR B).

The backtest built its equal-weight curve from raw closes and graded it against SPY,
so a Tokyo listing contributed its **yen** return: the exchange rate — often the larger
half of what a dollar investor actually got — was simply missing. With the primitive of
PR A (``data/fx.py``) every series is taken to ``PORTFOLIO.base_currency`` before it is
aligned with the benchmark.

The references are written from the definition. A stock that is flat in yen while the
yen appreciates 10 %/year against the dollar returned **10 %/year in dollars** to a dollar
investor; the old engine said 0 %. The CAGR is exact under the engine's own convention
(N weekly bars span N−1 weeks), so the oracle can be ``approx`` to a few decimals.

No network: ``get_history`` is stubbed in both modules that call it.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import analysis.backtesting as bt_mod
import data.fx as fx_mod
from analysis.backtesting import BacktestEngine, BacktestResult


@dataclass
class _Scored:
    """Duck-typed stand-in for a FundamentalResult, with the quote currency."""
    symbol: str
    adjusted_score: float
    currency: str = ""


N_BARS = 320


def _index():
    return pd.date_range(end=pd.Timestamp.now().normalize(), periods=N_BARS, freq="W-MON")


def _growing(start: float, annual_rate: float) -> pd.DataFrame:
    weekly = (1.0 + annual_rate) ** (1.0 / 52.0)
    return pd.DataFrame({"close": start * weekly ** np.arange(N_BARS)}, index=_index())


#: Local-currency closes. JPX.T and LDN.L are flat in their own currency.
PRICES = {
    "SPY": _growing(100.0, 0.08),
    "AAA": _growing(100.0, 0.15),
    "JPX.T": _growing(3000.0, 0.0),
    "LDN.L": _growing(3580.0, 0.0),
    "NOFX.T": _growing(3000.0, 0.0),
}
#: USD per unit of each currency. The yen appreciates 10 %/yr; the pound falls 5 %/yr.
FX = {
    "JPYUSD=X": _growing(0.0064, 0.10),
    "GBPUSD=X": _growing(1.30, -0.05),
}


@pytest.fixture
def stub(monkeypatch):
    calls: list[str] = []

    def _prices(symbol, period="5y", interval="1wk"):
        return PRICES.get(symbol, pd.DataFrame())

    def _fx(symbol, period="5y", interval="1wk"):
        calls.append(symbol)
        return FX.get(symbol, pd.DataFrame())

    monkeypatch.setattr(bt_mod, "get_history", _prices)
    monkeypatch.setattr(fx_mod, "get_history", _fx)
    return calls


def _run(results, **kw) -> BacktestResult:
    kw.setdefault("period_years", 5)
    kw.setdefault("rebalance_freq", "buy_and_hold")
    return BacktestEngine().run(results, top_n=kw.pop("top_n", 1), **kw)


def _ticker(result: BacktestResult, symbol: str):
    return next(t for t in result.ticker_results if t.symbol == symbol)


class TestTheCurrencyIsPartOfTheReturn:
    def test_flat_in_yen_with_the_yen_up_ten_percent_is_ten_percent_in_dollars(self, stub):
        r = _run([_Scored("JPX.T", 90, "JPY")])
        assert r.portfolio_cagr_pct == pytest.approx(10.0, abs=0.01)
        # The old engine said 0 %: the local return, with the exchange rate missing.
        assert r.portfolio_cagr_pct != pytest.approx(0.0, abs=1.0)

    def test_the_excess_over_spy_uses_the_dollar_return(self, stub):
        r = _run([_Scored("JPX.T", 90, "JPY")])
        assert r.excess_return_pct == pytest.approx(10.0 - 8.0, abs=0.01)

    def test_pence_and_a_falling_pound(self, stub):
        """Flat 3580 GBp with the pound −5 %/yr: −5 %/yr in dollars, whatever the ÷ 100."""
        r = _run([_Scored("LDN.L", 90, "GBp")])
        assert r.portfolio_cagr_pct == pytest.approx(-5.0, abs=0.01)

    def test_the_per_ticker_table_is_in_dollars_too(self, stub):
        r = _run([_Scored("JPX.T", 90, "JPY"), _Scored("AAA", 80, "USD")], top_n=2)
        assert _ticker(r, "JPX.T").cagr_pct == pytest.approx(10.0, abs=0.01)
        assert _ticker(r, "JPX.T").excess_return_pct == pytest.approx(2.0, abs=0.01)
        assert _ticker(r, "AAA").cagr_pct == pytest.approx(15.0, abs=0.01)
        assert {s["symbol"]: s["cagr_pct"] for s in r.score_vs_return}["JPX.T"] == (
            pytest.approx(10.0, abs=0.01)
        )

    def test_a_mixed_buy_and_hold_portfolio_matches_the_hand_calculation(self, stub):
        """Equal weight, no rebalancing: the mean of the two normalised dollar curves."""
        r = _run([_Scored("JPX.T", 90, "JPY"), _Scored("AAA", 80, "USD")], top_n=2)
        years = (N_BARS - 1) / 52
        end = (1.10 ** years + 1.15 ** years) / 2
        expected_cagr = (end ** (1 / years) - 1) * 100
        assert r.portfolio_cagr_pct == pytest.approx(expected_cagr, abs=0.05)


class TestWhatIsNotConverted:
    def test_a_dollar_ticker_does_not_fetch_any_rate(self, stub):
        r = _run([_Scored("AAA", 90, "USD")])
        assert stub == []
        assert r.portfolio_cagr_pct == pytest.approx(15.0, abs=0.01)
        assert r.converted_currencies == {}

    def test_an_unknown_currency_passes_as_it_came(self, stub):
        """Same contract as admission_skip_reason: what the writer does not know, does not block."""
        r = _run([_Scored("AAA", 90, "")])
        assert stub == []
        assert r.portfolio_cagr_pct == pytest.approx(15.0, abs=0.01)

    def test_a_ticker_without_a_rate_is_excluded_not_treated_as_dollars(self, stub):
        r = _run([_Scored("NOFX.T", 95, "CHF"), _Scored("AAA", 90, "USD")], top_n=2)
        # Its flat CHF curve must not enter the portfolio as a flat dollar curve.
        assert r.portfolio_cagr_pct == pytest.approx(15.0, abs=0.01)
        assert "NOFX.T" not in [t.symbol for t in r.ticker_results]
        assert any("NOFX.T" in n and "CHF" in n for n in r.notes)


class TestTheResultSaysWhatItConverted:
    def test_converted_tickers_and_their_currency_are_recorded(self, stub):
        r = _run([_Scored("JPX.T", 90, "JPY"), _Scored("LDN.L", 80, "GBp"),
                  _Scored("AAA", 70, "USD")], top_n=3)
        assert r.converted_currencies == {"JPX.T": "JPY", "LDN.L": "GBp"}
        assert any("JPX.T" in n and "USD" in n for n in r.notes)

    def test_the_record_survives_save_and_load(self, stub, tmp_path, monkeypatch):
        monkeypatch.setattr(bt_mod, "RESULTS_DIR", tmp_path)
        engine = BacktestEngine()
        r = engine.run([_Scored("JPX.T", 90, "JPY")], top_n=1, period_years=5,
                       rebalance_freq="buy_and_hold")
        loaded = BacktestEngine.load(engine.save(r))
        assert loaded.converted_currencies == {"JPX.T": "JPY"}

    def test_a_backtest_saved_before_the_field_still_loads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bt_mod, "RESULTS_DIR", tmp_path)
        r = BacktestResult(run_date="2026-09-01", period_years=5, start_date="2021-09-01",
                           end_date="2026-09-01", benchmark="SPY", top_n=1,
                           universe_size=1, rebalance_freq="annual")
        path = BacktestEngine().save(r)
        import json
        payload = json.loads(path.read_text())
        payload.pop("converted_currencies")
        path.write_text(json.dumps(payload))
        assert BacktestEngine.load(path).converted_currencies == {}


def test_the_rate_is_fetched_with_the_prices_period_and_interval(stub):
    with patch.object(fx_mod, "get_history", wraps=fx_mod.get_history) as spy:
        _run([_Scored("JPX.T", 90, "JPY")], period_years=3)
    spy.assert_called_with("JPYUSD=X", period="4y", interval="1wk")
