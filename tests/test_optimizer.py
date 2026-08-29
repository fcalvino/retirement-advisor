"""Tests for PortfolioOptimizer — pure-logic methods require no network calls."""

from __future__ import annotations

import zlib
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from config import OPTIMIZER
from portfolio.optimizer import _ETF_TICKERS, OptimizationResult, PortfolioOptimizer

# ------------------------------------------------------------------ #
#  Fixtures                                                            #
# ------------------------------------------------------------------ #

def _ticker(symbol: str, score: float = 65.0, div: float = 2.5, moat: float = 8.0,
            sector: str = "Technology", country: str = "United States") -> dict:
    # U5-16: exposure to the ARS discount comes from ``country``, not from the
    # symbol — a hardcoded list could not reach a ticker the user added by hand.
    return {
        "symbol": symbol,
        "adjusted_score": score,
        "dividend_yield": div,
        "moat_score": moat,
        "sector": sector,
        "country": country,
    }


def _make_tickers(n: int = 10, score: float = 65.0, sector: str = "Technology") -> list[dict]:
    syms = [f"XX{i:02d}" for i in range(n)]
    return [_ticker(s, score=score, sector=sector) for s in syms]


def _fake_price_history(sym, period="2y", interval="1wk"):
    """Return 2+ years of weekly prices to pass the min_obs check."""
    n = 110  # > 2 * 40 = 80 weeks required
    rng = np.random.default_rng(zlib.crc32(sym.encode()))  # stable across runs:
        # `hash()` is randomized per process (PYTHONHASHSEED), so seeding from it
        # regenerated different synthetic prices on every run and made this suite
        # non-reproducible — a green run proved nothing. Audit D4/D5.
    prices = 100.0 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
    dates = pd.date_range("2022-01-01", periods=n, freq="W")
    return pd.DataFrame({"close": prices}, index=dates)


# ------------------------------------------------------------------ #
#  Filtering                                                           #
# ------------------------------------------------------------------ #

class TestFilterEligible:
    def test_etf_tickers_excluded(self):
        opt = PortfolioOptimizer("conservative")
        tickers = [_ticker("SPY", score=80.0), _ticker("AAPL", score=70.0)]
        eligible, excluded = opt._filter_eligible(tickers)
        assert all(e[0] != "SPY" for e in excluded) is False  # SPY is excluded
        assert any(e[0] == "SPY" for e in excluded)
        assert all(t["symbol"] != "SPY" for t in eligible)

    def test_all_etfs_excluded(self):
        opt = PortfolioOptimizer("conservative")
        tickers = [_ticker(sym, score=80.0) for sym in list(_ETF_TICKERS)[:3]]
        eligible, excluded = opt._filter_eligible(tickers)
        assert eligible == []
        assert len(excluded) == 3

    def test_low_score_excluded(self):
        opt = PortfolioOptimizer("conservative")
        low_score = OPTIMIZER.min_score_threshold - 5.0
        tickers = [_ticker("AAPL", score=low_score)]
        eligible, excluded = opt._filter_eligible(tickers)
        assert eligible == []
        assert excluded[0][0] == "AAPL"

    def test_passing_score_included(self):
        opt = PortfolioOptimizer("conservative")
        tickers = [_ticker("AAPL", score=OPTIMIZER.min_score_threshold + 10.0)]
        eligible, excluded = opt._filter_eligible(tickers)
        assert len(eligible) == 1
        assert excluded == []

    def test_mixed_list(self):
        opt = PortfolioOptimizer("conservative")
        tickers = [
            _ticker("SPY", score=80.0),        # ETF → excluded
            _ticker("AAPL", score=70.0),        # pass
            _ticker("XX01", score=10.0),        # low score → excluded
        ]
        eligible, excluded = opt._filter_eligible(tickers)
        assert len(eligible) == 1
        assert eligible[0]["symbol"] == "AAPL"
        assert len(excluded) == 2

    def test_poor_data_quality_excluded(self):
        from config import DATA_QUALITY

        opt = PortfolioOptimizer("conservative")
        tickers = [
            _ticker("AAPL", score=70.0),
            {**_ticker("MSFT", score=75.0), "data_quality_level": "poor"},
        ]
        eligible, excluded = opt._filter_eligible(tickers)
        assert all(t["symbol"] != "MSFT" for t in eligible)
        assert any(e[0] == "MSFT" and "pobre" in e[1].lower() for e in excluded)
        assert DATA_QUALITY.exclude_poor_from_optimizer is True

    def test_partial_applies_score_haircut_without_mutating_input(self):
        from config import DATA_QUALITY

        opt = PortfolioOptimizer("conservative")
        original = {**_ticker("AAPL", score=80.0), "data_quality_level": "partial"}
        eligible, excluded = opt._filter_eligible([original])
        assert excluded == []
        assert len(eligible) == 1
        expected = round(80.0 * DATA_QUALITY.partial_optimizer_score_haircut, 4)
        assert eligible[0]["adjusted_score"] == expected
        assert original["adjusted_score"] == 80.0  # screener cache untouched
        assert eligible[0].get("_dq_partial_haircut") == DATA_QUALITY.partial_optimizer_score_haircut

    def test_nested_data_quality_dict_resolved(self):
        opt = PortfolioOptimizer("conservative")
        tickers = [
            {**_ticker("BAD", score=70.0), "data_quality": {"level": "poor"}},
        ]
        eligible, excluded = opt._filter_eligible(tickers)
        assert eligible == []
        assert excluded[0][0] == "BAD"


# ------------------------------------------------------------------ #
#  ARS Discount                                                        #
# ------------------------------------------------------------------ #

class TestArsDiscount:
    def test_ars_discount_applied_conservative(self):
        opt = PortfolioOptimizer("conservative")
        tickers = [_ticker("YPF", score=70.0, country="Argentina"),
                   _ticker("AAPL", score=70.0)]
        result = opt._apply_ars_discount(tickers)
        ypf = next(t for t in result if t["symbol"] == "YPF")
        aapl = next(t for t in result if t["symbol"] == "AAPL")
        assert ypf["adjusted_score"] < 70.0          # discounted
        assert aapl["adjusted_score"] == 70.0         # unchanged

    def test_ars_discount_applied_moderate(self):
        opt = PortfolioOptimizer("moderate")
        tickers = [_ticker("PAM", score=60.0, country="Argentina")]
        result = opt._apply_ars_discount(tickers)
        assert result[0]["adjusted_score"] < 60.0

    def test_ars_discount_not_applied_aggressive(self):
        opt = PortfolioOptimizer("aggressive")
        tickers = [_ticker("YPF", score=70.0, country="Argentina")]
        result = opt._apply_ars_discount(tickers)
        assert result[0]["adjusted_score"] == 70.0

    def test_discount_factor_matches_config(self):
        opt = PortfolioOptimizer("conservative")
        tickers = [_ticker("YPF", score=100.0, country="Argentina")]
        result = opt._apply_ars_discount(tickers)
        expected = 100.0 * OPTIMIZER.ars_risk_discount
        assert abs(result[0]["adjusted_score"] - expected) < 0.01

    def test_non_ars_tickers_unchanged(self):
        opt = PortfolioOptimizer("conservative")
        tickers = [_ticker("MSFT", score=80.0), _ticker("JNJ", score=75.0)]
        result = opt._apply_ars_discount(tickers)
        for t in result:
            assert t["adjusted_score"] in (80.0, 75.0)


# ------------------------------------------------------------------ #
#  Expected returns                                                    #
# ------------------------------------------------------------------ #

class TestExpectedReturns:
    def test_returns_array_length_matches_tickers(self):
        opt = PortfolioOptimizer("moderate")
        tickers = _make_tickers(5)
        mu = opt._expected_returns(tickers)
        assert len(mu) == 5

    def test_higher_score_gives_higher_return(self):
        opt = PortfolioOptimizer("conservative")
        t_high = [_ticker("A", score=90.0, div=2.0, moat=10.0)]
        t_low  = [_ticker("B", score=40.0, div=2.0, moat=10.0)]
        assert opt._expected_returns(t_high)[0] > opt._expected_returns(t_low)[0]

    def test_higher_dividend_gives_higher_return(self):
        opt = PortfolioOptimizer("conservative")
        t_high = [_ticker("A", score=65.0, div=5.0, moat=8.0)]
        t_low  = [_ticker("B", score=65.0, div=1.0, moat=8.0)]
        assert opt._expected_returns(t_high)[0] > opt._expected_returns(t_low)[0]

    def test_returns_all_positive_for_valid_tickers(self):
        opt = PortfolioOptimizer("moderate")
        tickers = _make_tickers(8)
        mu = opt._expected_returns(tickers)
        assert np.all(mu > 0)

    def test_suspicious_div_yield_capped(self):
        """Div yield > 15% (bad data) should be treated as 0."""
        opt = PortfolioOptimizer("moderate")
        t_bad = [_ticker("X", score=65.0, div=50.0, moat=8.0)]
        t_ok  = [_ticker("X", score=65.0, div=0.0,  moat=8.0)]
        mu_bad = opt._expected_returns(t_bad)[0]
        mu_ok  = opt._expected_returns(t_ok)[0]
        assert abs(mu_bad - mu_ok) < 1e-6

    def test_er_absolute_cap_enforced(self):
        """P2 D4: even max score/moat/div cannot exceed OPTIMIZER.er_absolute_cap."""
        from config import OPTIMIZER

        opt = PortfolioOptimizer("aggressive")
        t = [_ticker("MAX", score=100.0, div=10.0, moat=20.0)]
        mu = opt._expected_returns(t)[0]
        cap = float(OPTIMIZER.er_absolute_cap)
        assert cap > 0
        assert mu <= cap + 1e-9
        # Ranking still works under the cap
        t_high = [_ticker("A", score=90.0, div=2.0, moat=10.0)]
        t_low = [_ticker("B", score=40.0, div=2.0, moat=10.0)]
        assert opt._expected_returns(t_high)[0] > opt._expected_returns(t_low)[0]

    def test_er_cap_disabled_allows_higher(self):
        """er_absolute_cap=0 disables the ceiling; a binding cap clamps μ.

        Tested against a deliberately low cap rather than the shipped 14%:
        since the 2026-08 D3 fix the view weights are global, so the highest μ
        the proxy can produce is 13% and the shipped cap never binds. It stays
        as a guardrail for future weight changes — see OptimizerConfig.
        """
        from unittest.mock import patch

        from config import OPTIMIZER

        opt = PortfolioOptimizer("aggressive")
        t = [_ticker("MAX", score=100.0, div=10.0, moat=20.0)]

        with patch.object(OPTIMIZER, "er_absolute_cap", 0.05):
            capped = opt._expected_returns(t)[0]
        with patch.object(OPTIMIZER, "er_absolute_cap", 0.0):
            uncapped = opt._expected_returns(t)[0]

        assert capped == pytest.approx(0.05)
        assert uncapped > capped


# ------------------------------------------------------------------ #
#  Clean div yield                                                     #
# ------------------------------------------------------------------ #

class TestCleanDivYield:
    @pytest.mark.parametrize("raw,expected", [
        (3.5, 3.5),
        (0.0, 0.0),
        (15.0, 15.0),
        (15.1, 0.0),   # over cap
        (50.0, 0.0),   # yfinance garbage
        (-1.0, 0.0),   # negative
    ])
    def test_capping(self, raw, expected):
        assert PortfolioOptimizer._clean_div_yield(raw) == expected


# ------------------------------------------------------------------ #
#  Score-weighted fallback                                             #
# ------------------------------------------------------------------ #

class TestScoreWeightedOptimize:
    def test_weights_sum_to_one(self):
        opt = PortfolioOptimizer("conservative")
        tickers = _make_tickers(10)
        w = opt._score_weighted_optimize(tickers)
        assert abs(w.sum() - 1.0) < 1e-6

    def test_all_weights_positive(self):
        opt = PortfolioOptimizer("conservative")
        tickers = _make_tickers(6)
        w = opt._score_weighted_optimize(tickers)
        assert np.all(w >= 0)

    def test_max_weight_respects_profile_cap(self):
        # Use aggressive profile (18% cap) with 8 equal-score tickers (1/8=12.5% < 18%)
        # so iterative clipping converges cleanly.
        opt = PortfolioOptimizer("aggressive")
        tickers = _make_tickers(8)
        w = opt._score_weighted_optimize(tickers)
        ub = opt.cfg.max_position_pct / 100
        assert np.all(w <= ub + 1e-6)

    def test_higher_score_gets_larger_weight(self):
        """With unequal scores, the higher-score ticker should get more weight."""
        opt = PortfolioOptimizer("aggressive")
        tickers = [
            _ticker("A", score=90.0),
            _ticker("B", score=90.0),
            _ticker("C", score=90.0),
            _ticker("D", score=90.0),
            _ticker("E", score=90.0),
            _ticker("HIGHSCORE", score=90.0),
        ]
        # Make one ticker have a clearly higher score
        tickers[-1]["adjusted_score"] = 150.0  # artificially high
        w = opt._score_weighted_optimize(tickers)
        assert w[-1] > w[0]  # HIGHSCORE > others


# ------------------------------------------------------------------ #
#  Rebalance frequency                                                 #
# ------------------------------------------------------------------ #

class TestRebalanceFrequency:
    def _result_with_vol(self, vol: float) -> OptimizationResult:
        r = OptimizationResult(profile_name="Test", method="score-weighted")
        r.volatility_pct = vol
        return r

    def test_conservative_low_vol_annual(self):
        opt = PortfolioOptimizer("conservative")
        freq, _ = opt._suggest_rebalance_frequency(self._result_with_vol(10.0))
        assert freq == "Anual"

    def test_conservative_high_vol_semiannual(self):
        opt = PortfolioOptimizer("conservative")
        freq, _ = opt._suggest_rebalance_frequency(self._result_with_vol(20.0))
        assert freq == "Semestral"

    def test_moderate_low_vol_semiannual(self):
        opt = PortfolioOptimizer("moderate")
        freq, _ = opt._suggest_rebalance_frequency(self._result_with_vol(14.0))
        assert freq == "Semestral"

    def test_moderate_high_vol_trimestral(self):
        opt = PortfolioOptimizer("moderate")
        freq, _ = opt._suggest_rebalance_frequency(self._result_with_vol(22.0))
        assert freq == "Trimestral"

    def test_aggressive_always_trimestral(self):
        opt = PortfolioOptimizer("aggressive")
        for vol in [10.0, 18.0, 30.0]:
            freq, _ = opt._suggest_rebalance_frequency(self._result_with_vol(vol))
            assert freq == "Trimestral"

    def test_rationale_not_empty(self):
        opt = PortfolioOptimizer("moderate")
        _, rationale = opt._suggest_rebalance_frequency(self._result_with_vol(15.0))
        assert len(rationale) > 10


# ------------------------------------------------------------------ #
#  Rebalancing suggestions                                             #
# ------------------------------------------------------------------ #

class TestRebalancingSuggestions:
    def _opt(self):
        return PortfolioOptimizer("moderate")

    def test_buy_when_target_greater_than_current(self):
        opt = self._opt()
        suggestions = opt._rebalancing_suggestions(
            target_weights={"AAPL": 15.0},
            current_weights={"AAPL": 5.0},
        )
        aapl = next(s for s in suggestions if s.symbol == "AAPL")
        assert aapl.action == "BUY"
        assert aapl.delta_pct > 0

    def test_sell_when_target_less_than_current(self):
        opt = self._opt()
        suggestions = opt._rebalancing_suggestions(
            target_weights={"T": 3.0},
            current_weights={"T": 12.0},
        )
        t = next(s for s in suggestions if s.symbol == "T")
        assert t.action == "SELL"
        assert t.delta_pct < 0

    def test_tiny_delta_is_hold(self):
        opt = self._opt()
        suggestions = opt._rebalancing_suggestions(
            target_weights={"JPM": 10.0},
            current_weights={"JPM": 10.3},  # only 0.3% delta
        )
        # delta < 0.5% → HOLD
        if suggestions:
            jpmorgan = next((s for s in suggestions if s.symbol == "JPM"), None)
            if jpmorgan:
                assert jpmorgan.action == "HOLD"

    def test_new_position_shows_as_buy(self):
        opt = self._opt()
        suggestions = opt._rebalancing_suggestions(
            target_weights={"NVDA": 8.0},
            current_weights={},
        )
        nvda = next(s for s in suggestions if s.symbol == "NVDA")
        assert nvda.action == "BUY"
        assert nvda.current_pct == 0.0

    def test_exited_position_shows_as_sell(self):
        opt = self._opt()
        suggestions = opt._rebalancing_suggestions(
            target_weights={},
            current_weights={"META": 6.0},
        )
        meta = next(s for s in suggestions if s.symbol == "META")
        assert meta.action == "SELL"
        assert meta.target_pct == 0.0


# ------------------------------------------------------------------ #
#  Full optimize (mocked fetcher)                                      #
# ------------------------------------------------------------------ #

class TestFullOptimize:
    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_optimize_returns_result_object(self, _mock):
        opt = PortfolioOptimizer("aggressive")
        tickers = [_ticker(f"S{i:02d}", score=65.0 + i, div=2.0, sector="Technology") for i in range(8)]
        result = opt.optimize(tickers)
        assert isinstance(result, OptimizationResult)

    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_weights_sum_to_100(self, _mock):
        opt = PortfolioOptimizer("aggressive")
        tickers = [_ticker(f"S{i:02d}", score=65.0, div=2.0, sector="Technology") for i in range(8)]
        result = opt.optimize(tickers)
        total = sum(a.weight_pct for a in result.tickers)
        assert abs(total - 100.0) < 0.5

    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_rebalance_frequency_set(self, _mock):
        opt = PortfolioOptimizer("moderate")
        tickers = [_ticker(f"S{i:02d}", score=65.0, div=2.0, sector="Technology") for i in range(8)]
        result = opt.optimize(tickers)
        assert result.rebalance_frequency in ("Anual", "Semestral", "Trimestral")

    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_insufficient_tickers_returns_result_with_warning(self, _mock):
        opt = PortfolioOptimizer("conservative")
        # Only one non-ETF, non-low-score ticker → not enough to optimize
        result = opt.optimize([_ticker("AAPL", score=70.0)])
        assert len(result.warnings) > 0

    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_instrumentation_fields_populated(self, _mock):
        opt = PortfolioOptimizer("aggressive")
        tickers = [_ticker(f"S{i:02d}", score=65.0, div=2.0, sector="Technology") for i in range(8)]
        result = opt.optimize(tickers)
        assert result.n_input == 8
        assert result.n_eligible >= 0
        assert result.n_candidates >= 0
        assert result.build_matrix_ms >= 0.0


# ------------------------------------------------------------------ #
#  Profile candidate down-select (Fase C)                              #
# ------------------------------------------------------------------ #

class TestSelectCandidatesForProfile:
    def test_no_downselect_when_below_topk(self):
        opt = PortfolioOptimizer("conservative")  # pre_filter_top_k=20
        tickers = _make_tickers(10)
        result = opt._select_candidates_for_profile(tickers)
        assert len(result) == 10  # fewer than top_k, no truncation

    def test_downselect_when_above_topk(self):
        opt = PortfolioOptimizer("conservative")  # pre_filter_top_k=20
        tickers = _make_tickers(50)
        result = opt._select_candidates_for_profile(tickers)
        assert len(result) <= opt.cfg.pre_filter_top_k

    def test_conservative_profile_favors_dividends(self):
        # Conservative has high dividend_weight=0.45; should prefer high-div tickers
        opt = PortfolioOptimizer("conservative")
        high_div = [_ticker(f"HD{i:02d}", score=65.0, div=5.0, moat=8.0, sector="Financials") for i in range(10)]
        low_div  = [_ticker(f"LD{i:02d}", score=65.0, div=0.5, moat=8.0, sector="Technology") for i in range(30)]
        tickers  = high_div + low_div  # 40 total, top_k=20
        result   = opt._select_candidates_for_profile(tickers)
        selected_syms = {t["symbol"] for t in result}
        # At least 8 of the 10 high-div tickers should make the cut
        hd_selected = sum(1 for t in high_div if t["symbol"] in selected_syms)
        assert hd_selected >= 8

    def test_aggressive_profile_has_larger_topk(self):
        opt_cons = PortfolioOptimizer("conservative")
        opt_agg  = PortfolioOptimizer("aggressive")
        assert opt_agg.cfg.pre_filter_top_k > opt_cons.cfg.pre_filter_top_k

    def test_min_positions_always_preserved(self):
        opt = PortfolioOptimizer("conservative")
        # Even with a huge universe, we keep at least min_positions+2
        tickers = _make_tickers(100)
        result  = opt._select_candidates_for_profile(tickers)
        assert len(result) >= opt.cfg.min_positions


# ------------------------------------------------------------------ #
#  Deterministic core holdings (Fase C / Fase B fallback)             #
# ------------------------------------------------------------------ #

class TestSelectCoreHoldings:
    def _make_allocations(self, n=15):
        from portfolio.optimizer import TickerAllocation
        allocs = []
        for i in range(n):
            allocs.append(TickerAllocation(
                symbol=f"T{i:02d}",
                weight_pct=round(100.0 / n, 1),
                expected_return_pct=8.0,
                volatility_pct=12.0,
                dividend_yield_pct=2.5,
                adjusted_score=65.0 + i,
                moat_score=8.0,
                sector="Technology",
            ))
        return allocs

    def test_core_length_bounded_by_target(self):
        opt = PortfolioOptimizer("conservative")  # target_max_human_positions=10
        allocs = self._make_allocations(20)
        core = opt._select_core_holdings(allocs)
        assert len(core) <= opt.cfg.target_max_human_positions

    def test_core_weights_sum_to_100(self):
        opt = PortfolioOptimizer("moderate")
        allocs = self._make_allocations(20)
        core = opt._select_core_holdings(allocs)
        total = sum(c["suggested_weight_pct"] for c in core)
        assert abs(total - 100.0) < 0.5

    def test_core_has_required_keys(self):
        opt = PortfolioOptimizer("aggressive")
        allocs = self._make_allocations(10)
        core = opt._select_core_holdings(allocs)
        for item in core:
            assert "symbol" in item
            assert "suggested_weight_pct" in item
            assert "why" in item

    def test_empty_allocations_returns_empty(self):
        opt = PortfolioOptimizer("conservative")
        assert opt._select_core_holdings([]) == []

    def test_core_fewer_than_full_for_large_portfolio(self):
        opt = PortfolioOptimizer("conservative")  # target=10
        allocs = self._make_allocations(25)
        core = opt._select_core_holdings(allocs)
        assert len(core) < len(allocs)

    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_profile_core_populated_in_full_optimize(self, _mock):
        """profile_core_holdings is always set by optimize(), no LLM needed."""
        opt = PortfolioOptimizer("conservative")
        tickers = [
            _ticker(f"S{i:02d}", score=65.0, div=3.5, moat=8.0, sector="Financials")
            for i in range(15)
        ]
        result = opt.optimize(tickers)
        assert isinstance(result.profile_core_holdings, list)
        assert len(result.profile_core_holdings) > 0
        # Core should be smaller than or equal to full result
        assert len(result.profile_core_holdings) <= len(result.tickers)


# ------------------------------------------------------------------ #
#  Large-N behaviour                                                   #
# ------------------------------------------------------------------ #

class TestLargeN:
    """Verify that the optimizer handles large universes without crashing
    and produces manageable outputs respecting the profile constraints."""

    def _make_diverse_tickers(self, n: int) -> list[dict]:
        sectors = ["Technology", "Financials", "Healthcare", "Consumer Staples",
                   "Energy", "Industrials", "Telecom / REIT"]
        return [
            _ticker(
                f"LN{i:03d}",
                score=45.0 + (i % 40),
                div=0.5 + (i % 6) * 0.8,
                moat=4.0 + (i % 10),
                sector=sectors[i % len(sectors)],
            )
            for i in range(n)
        ]

    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_large_n_conservative_produces_manageable_result(self, _mock):
        opt = PortfolioOptimizer("conservative")  # pre_filter_top_k=20
        tickers = self._make_diverse_tickers(80)
        result = opt.optimize(tickers)
        assert isinstance(result, OptimizationResult)
        assert result.n_input == 80
        assert result.n_candidates <= opt.cfg.pre_filter_top_k

    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_large_n_different_profiles_produce_different_candidates(self, _mock):
        tickers = self._make_diverse_tickers(60)
        r_cons = PortfolioOptimizer("conservative").optimize(tickers)
        r_agg  = PortfolioOptimizer("aggressive").optimize(tickers)
        # Conservative pre_filter_top_k=20, aggressive=45 → different candidate counts
        assert r_cons.n_candidates <= 20
        assert r_agg.n_candidates <= 45
        # Conservative should generally have fewer positions than aggressive
        # (both are bounded, but aggressive allows more)
        assert r_cons.n_candidates <= r_agg.n_candidates

    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_core_holdings_always_present_for_large_n(self, _mock):
        opt = PortfolioOptimizer("moderate")
        tickers = self._make_diverse_tickers(50)
        result = opt.optimize(tickers)
        assert len(result.profile_core_holdings) > 0
        assert len(result.profile_core_holdings) <= opt.cfg.target_max_human_positions

    @patch("portfolio.optimizer.get_history", side_effect=_fake_price_history)
    def test_instrumentation_fields_for_large_n(self, _mock):
        opt = PortfolioOptimizer("aggressive")
        tickers = self._make_diverse_tickers(70)
        result = opt.optimize(tickers)
        assert result.n_input == 70
        assert result.n_eligible <= 70
        assert result.n_candidates <= opt.cfg.pre_filter_top_k
        assert result.build_matrix_ms >= 0
