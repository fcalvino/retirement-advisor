"""Oracle tests for converting a price series in its quote currency to USD (#154, PR A).

Issue #154 (Optimizer, Backtesting and Track Record on multi-currency universes)
---------------------------------------------------------------------------------
  hallazgo : ``global_quality`` has 90 of 126 tickers quoted in a non-USD currency (14
             of them). The Optimizer, Backtesting and Track Record read raw prices, so a
             JPY return, a GBp return and a USD return are averaged as if they were one.
  criterio : "Un retorno en JPY y uno en USD, convertidos, dan el mismo exceso que un
             oráculo calculado a mano."

This file covers the primitive only (``data/fx.py``); nothing consumes it yet, so no
published number moves. The references below are written by hand from the definition —
price in USD = price in quote currency × USD per unit of that currency — never from the
production source: comparing the code against itself freezes a bug instead of finding it
(CONTEXT.md §5).

What the measurement of 2026-09-29 added, and what this file pins
------------------------------------------------------------------
Yahoo's FX history carries **single bad prints that revert**: CLPUSD=X was 0.2 on
2016-12-22 (it is ~0.0015), NOKUSD=X +39 % on 2020-03-20, CADUSD=X three weeks in
2022-11, 2024-12 and 2025-01 (RY.TO's annual volatility came out +4.95 pp too high).
The series below are the real ones, copied from that measurement. The guard drops a
point that sits ≥ ``FX.spike_dev_pct`` away from the geometric midpoint of its neighbours
*and* whose neighbours agree with each other; a real step (1.0 → 1.3, staying) and a real
crisis rebound (AUD, week of 2020-03-16: −8.5 %, net −3.1 %) must survive.

No network, no Streamlit.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from config import FX, PORTFOLIO
from data import fx as fxmod

ROOT = Path(__file__).resolve().parents[1]


def _series(values, dates):
    return pd.Series(values, index=pd.to_datetime(dates), dtype=float)


def _weekly(values, start="2024-01-01"):
    return _series(values, pd.date_range(start, periods=len(values), freq="W-MON"))


def _kept(values):
    """Indexes of ``values`` that survive the guard (the series index is 0..n-1)."""
    s = pd.Series(values, index=range(len(values)), dtype=float)
    return list(fxmod.drop_fx_spikes(s).index)


# --------------------------------------------------------------------------- #
#  The conversion itself: price × USD-per-unit, from the definition            #
# --------------------------------------------------------------------------- #


class TestConversion:
    def test_jpy_return_matches_the_hand_calculation(self):
        """The acceptance criterion of #154: a JPY return, converted, by hand."""
        px = _weekly([3000.0, 3100.0])
        fx = _weekly([0.0064, 0.0066])
        out = fxmod.to_base_currency(px, "JPY", fx)
        assert out.iloc[0] == pytest.approx(3000 * 0.0064)  # 19.2 USD
        expected_return = (3100 * 0.0066) / (3000 * 0.0064) - 1  # +6.5625 %
        assert out.iloc[1] / out.iloc[0] - 1 == pytest.approx(expected_return)
        # The local return (+3.33 %) is a different number: the currency is not noise.
        assert expected_return != pytest.approx(3100 / 3000 - 1)

    def test_pence_are_divided_by_a_hundred_before_the_pound_rate(self):
        """SHEL.L quotes 3580 GBp: 35.80 GBP × 1.30 = 46.54 USD, not 4654."""
        out = fxmod.to_base_currency(_weekly([3580.0]), "GBp", _weekly([1.30]))
        assert out.iloc[0] == pytest.approx(3580 / 100 * 1.30)

    def test_a_minor_unit_of_the_base_currency_is_only_divided(self, monkeypatch):
        """Base GBP: 3580 GBp is 35.80 GBP, and there is no pair to fetch."""
        monkeypatch.setattr(PORTFOLIO, "base_currency", "GBP")
        out = fxmod.to_base_currency(_weekly([3580.0]), "GBp", None)
        assert out.iloc[0] == pytest.approx(35.80)

    def test_base_currency_and_unknown_currency_pass_through(self):
        """Same contract as ``admission_skip_reason``: an unknown currency does not block."""
        px = _weekly([10.0, 11.0, 12.0])
        for ccy in (PORTFOLIO.base_currency, "", None):
            out = fxmod.to_base_currency(px, ccy, None)
            pd.testing.assert_series_equal(out, px)

    def test_a_missing_rate_is_none_never_one(self):
        """U2-4 again: 'no rate' must not become a rate of 1.0."""
        px = _weekly([3000.0, 3100.0])
        assert fxmod.to_base_currency(px, "JPY", None) is None
        assert fxmod.to_base_currency(px, "JPY", pd.Series(dtype=float)) is None

    def test_a_date_without_a_rate_is_dropped_not_converted_at_one(self):
        px = _series([100.0, 100.0, 100.0, 100.0],
                     ["2024-01-01", "2024-01-08", "2024-01-12", "2024-01-29"])
        fx = _series([1.10, 1.20], ["2024-01-01", "2024-01-08"])
        out = fxmod.to_base_currency(px, "EUR", fx)
        assert list(out.index.strftime("%Y-%m-%d")) == ["2024-01-01", "2024-01-08", "2024-01-12"]
        # 01-12 is 4 days after the last rate (inside FX.max_staleness_days): carried.
        assert out.iloc[2] == pytest.approx(100 * 1.20)
        # 01-29 is 21 days after it: no rate, no price — not 100 × 1.0.
        assert pd.Timestamp("2024-01-29") not in out.index

    def test_the_input_is_not_mutated(self):
        px = _weekly([3000.0, 3100.0])
        before = px.copy()
        fxmod.to_base_currency(px, "JPY", _weekly([0.0064, 0.0066]))
        pd.testing.assert_series_equal(px, before)


# --------------------------------------------------------------------------- #
#  The spike guard — real series from the 2026-09-29 measurement               #
# --------------------------------------------------------------------------- #


class TestSpikeGuard:
    def test_clp_2016_12_22_print_of_0_2_is_dropped(self):
        real = [0.001485, 0.001505, 0.001507, 0.2, 0.001507, 0.001484]
        assert _kept(real) == [0, 1, 2, 4, 5]

    def test_cad_weekly_2022_11_is_dropped_and_its_neighbours_are_not(self):
        real = [0.7397, 0.742, 0.8732, 0.7455, 0.7463]
        assert _kept(real) == [0, 1, 3, 4]

    def test_nok_2020_03_20_is_dropped_although_its_neighbours_differ_8_percent(self):
        """A 'net ≤ 2 %' rule missed this one: the real move that week was −8.3 %."""
        real = [0.098699, 0.097383, 0.096431, 0.092772, 0.129277, 0.085035, 0.087133, 0.090707]
        assert _kept(real) == [0, 1, 2, 3, 5, 6, 7]

    def test_a_persistent_step_is_a_move_not_a_print(self):
        assert _kept([1.0, 1.0, 1.3, 1.3]) == [0, 1, 2, 3]

    def test_the_aud_crisis_rebound_survives(self):
        """Week of 2020-03-16: −8.5 %, then back to −3.1 % net. Real, not a bad print."""
        assert _kept([0.6408, 0.5863, 0.6209]) == [0, 1, 2]

    def test_the_cut_is_ten_percent_of_deviation(self):
        assert _kept([1.0, 1.099, 1.0]) == [0, 1, 2]   # 9.9 %: kept
        assert _kept([1.0, 1.101, 1.0]) == [0, 2]      # 10.1 %: dropped

    def test_the_first_and_the_last_point_are_not_judged(self):
        assert _kept([1.0, 1.0, 1.0, 5.0]) == [0, 1, 2, 3]
        assert _kept([5.0, 1.0, 1.0, 1.0]) == [0, 1, 2, 3]

    def test_short_or_empty_series_are_returned_as_they_are(self):
        assert list(fxmod.drop_fx_spikes(pd.Series(dtype=float)).index) == []
        assert _kept([1.0, 50.0]) == [0, 1]

    def test_the_cuts_come_from_config(self, monkeypatch):
        cad = [0.7397, 0.742, 0.8732, 0.7455, 0.7463]
        monkeypatch.setattr(FX, "spike_dev_pct", 50.0)
        assert _kept(cad) == [0, 1, 2, 3, 4]
        monkeypatch.setattr(FX, "spike_dev_pct", 10.0)
        monkeypatch.setattr(FX, "spike_neighbor_agreement", 0.0)
        nok = [0.098699, 0.097383, 0.096431, 0.092772, 0.129277, 0.085035, 0.087133]
        assert 4 in _kept(nok)                      # neighbours −8.3 % apart: no longer 'agree'
        clp = [0.001485, 0.001505, 0.001507, 0.2, 0.001507, 0.001484]
        assert 3 not in _kept(clp)                  # neighbours identical: still dropped


# --------------------------------------------------------------------------- #
#  Symbols and the fetch path                                                  #
# --------------------------------------------------------------------------- #


class TestPairSymbol:
    @pytest.mark.parametrize(
        "ccy, expected",
        [("EUR", "EURUSD=X"), ("JPY", "JPYUSD=X"), ("GBp", "GBPUSD=X"), ("GBP", "GBPUSD=X"),
         ("CLP", "CLPUSD=X"), ("USD", None), ("", None), (None, None)],
    )
    def test_pair_symbol(self, ccy, expected):
        assert fxmod.fx_pair_symbol(ccy) == expected

    def test_the_target_is_the_portfolio_base_currency(self, monkeypatch):
        monkeypatch.setattr(PORTFOLIO, "base_currency", "EUR")
        assert fxmod.fx_pair_symbol("JPY") == "JPYEUR=X"
        assert fxmod.fx_pair_symbol("EUR") is None

    def test_no_usd_literal_in_the_module(self):
        """One number written twice is two numbers: the destination lives in ``PORTFOLIO``."""
        tree = ast.parse((ROOT / "data" / "fx.py").read_text(encoding="utf-8"))
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert "USD" not in literals
        assert not [s for s in literals if s.endswith("USD=X")]


def _frame(values, dates):
    """What ``get_history`` returns: a DatetimeIndex named Date, lower-case columns."""
    df = pd.DataFrame({"close": values}, index=pd.to_datetime(dates))
    df.index.name = "Date"
    return df


class TestFetchPath:
    def test_the_pair_is_requested_with_the_same_period_and_interval_as_the_prices(self):
        fx_frame = _frame([1.10, 1.11], ["2024-01-01", "2024-01-08"])
        with patch("data.fx.get_history", return_value=fx_frame) as gh:
            fxmod.get_fx_history("EUR", period="10y", interval="1wk")
        gh.assert_called_once_with("EURUSD=X", period="10y", interval="1wk")

    def test_the_base_currency_does_not_fetch_anything(self):
        with patch("data.fx.get_history") as gh:
            assert fxmod.get_fx_history("USD", period="10y", interval="1wk") is None
        gh.assert_not_called()

    def test_end_to_end_the_cad_glitch_week_carries_the_previous_rate(self):
        """100 CAD flat every week; the 0.8732 week is a bad print, so it is priced at 0.742."""
        dates = pd.date_range("2022-10-24", periods=5, freq="W-MON")
        rates = [0.7397, 0.742, 0.8732, 0.7455, 0.7463]
        with patch("data.fx.get_history", return_value=_frame(rates, dates)):
            out = fxmod.convert_history(_series([100.0] * 5, dates), "CAD",
                                        period="10y", interval="1wk")
        expected = [100 * 0.7397, 100 * 0.742, 100 * 0.742, 100 * 0.7455, 100 * 0.7463]
        assert list(out.values) == pytest.approx(expected)

    def test_without_the_guard_the_glitch_would_inflate_the_return(self):
        """The reason the guard exists: the raw week is +17.7 % in USD on a flat stock."""
        raw = 0.8732 / 0.742 - 1
        assert raw == pytest.approx(0.177, abs=1e-3)

    def test_an_empty_history_gives_none(self):
        with patch("data.fx.get_history", return_value=pd.DataFrame()):
            assert fxmod.convert_history(_weekly([100.0, 101.0]), "EUR",
                                         period="10y", interval="1wk") is None

    def test_a_frame_without_a_close_column_gives_none(self):
        bad = pd.DataFrame({"open": [1.0]}, index=pd.to_datetime(["2024-01-01"]))
        with patch("data.fx.get_history", return_value=bad):
            assert fxmod.get_fx_history("EUR", period="10y", interval="1wk") is None

    def test_a_base_currency_series_is_returned_unconverted(self):
        px = _weekly([10.0, 11.0])
        with patch("data.fx.get_history") as gh:
            out = fxmod.convert_history(px, "USD", period="10y", interval="1wk")
        gh.assert_not_called()
        pd.testing.assert_series_equal(out, px)
