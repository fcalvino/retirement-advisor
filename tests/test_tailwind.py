"""Tests for the sector-country structural tailwind layer (Idea 2)."""

from __future__ import annotations

import json
import zlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from analysis.tailwind import (
    TailwindAnalyzer,
    classify_tailwind,
    compute_tailwind_bonus,
    invalidate_curated_cache,
    load_curated_tailwinds,
)
from config import TAILWINDS, AIConfig, TailwindConfig

# ------------------------------------------------------------------ #
#  Fixtures                                                            #
# ------------------------------------------------------------------ #

_ENTRIES = {
    "entries": [
        {
            "key": "energy-ar",
            "sector": "Energy",
            "country": "Argentina",
            "tickers": ["YPF", "PAM"],
            "score": 8.0,
            "durability_years": 10,
            "rationale": "Vaca Muerta ramp",
            "last_reviewed": "2026-06",
        },
        {
            "key": "tech-us",
            "sector": "Technology",
            "country": "United States",
            "score": 4.0,
            "durability_years": 6,
            "rationale": "AI capex cycle",
        },
        {
            "key": "reg-elec-ar",
            "sector": "Utilities",
            "industry": "Utilities - Regulated Electric",
            "country": "Argentina",
            "score": -3.0,
            "durability_years": 5,
            "rationale": "Tarifas congeladas",
        },
    ]
}


@pytest.fixture
def data_file(tmp_path):
    p = tmp_path / "tailwinds.json"
    p.write_text(json.dumps(_ENTRIES), encoding="utf-8")
    invalidate_curated_cache()
    yield p
    invalidate_curated_cache()


@pytest.fixture
def analyzer(data_file):
    return TailwindAnalyzer(data_path=data_file)


# ------------------------------------------------------------------ #
#  Pure functions: classification + bonus                              #
# ------------------------------------------------------------------ #

class TestClassification:
    def test_thresholds(self):
        assert classify_tailwind(10.0) == "Strong"
        assert classify_tailwind(TAILWINDS.strong_threshold) == "Strong"
        assert classify_tailwind(TAILWINDS.moderate_threshold) == "Moderate"
        assert classify_tailwind(0.0) == "Neutral"
        assert classify_tailwind(TAILWINDS.headwind_threshold) == "Headwind"
        assert classify_tailwind(-5.0) == "Headwind"

    def test_bonus_capped_positive(self):
        assert compute_tailwind_bonus(10.0) == TAILWINDS.max_bonus
        assert compute_tailwind_bonus(8.0) == round(8.0 * TAILWINDS.bonus_factor, 1)

    def test_bonus_capped_negative(self):
        big_head = compute_tailwind_bonus(-100.0)
        assert big_head == -TAILWINDS.max_bonus
        assert compute_tailwind_bonus(-3.0) == round(-3.0 * TAILWINDS.bonus_factor, 1)

    def test_neutral_score_zero_bonus(self):
        assert compute_tailwind_bonus(0.0) == 0.0

    def test_config_change_takes_effect_without_code_edit(self):
        cfg = TailwindConfig(max_bonus=2.0, bonus_factor=1.0, strong_threshold=1.0)
        assert compute_tailwind_bonus(8.0, cfg) == 2.0
        assert classify_tailwind(1.5, cfg) == "Strong"


# ------------------------------------------------------------------ #
#  Curated matching                                                    #
# ------------------------------------------------------------------ #

class TestCuratedMatching:
    def test_ticker_override_wins(self, analyzer):
        # PAM is yfinance-sector Utilities but listed in the energy entry tickers
        d = analyzer.analyze("PAM", sector="Utilities", country="Argentina",
                             industry="Utilities - Independent Power Producers")
        assert d.classification == "Strong"
        assert d.matched_on == "ticker"
        assert d.bonus > 0
        assert d.durability_years == 10
        assert "Vaca Muerta" in d.explanation

    def test_sector_country_match(self, analyzer):
        d = analyzer.analyze("MSFT", sector="Technology", country="United States",
                             industry="Software - Infrastructure")
        assert d.classification == "Moderate"
        assert d.matched_on == "sector"

    def test_industry_match_beats_sector(self, analyzer):
        d = analyzer.analyze("XXAR", sector="Utilities", country="Argentina",
                             industry="Utilities - Regulated Electric")
        assert d.classification == "Headwind"
        assert d.matched_on == "industry"
        assert d.bonus < 0

    def test_uncovered_pair_is_neutral(self, analyzer):
        d = analyzer.analyze("XOM", sector="Energy", country="United States")
        assert d.classification == "Neutral"
        assert d.bonus == 0.0
        assert d.tailwind_score == 0.0

    def test_missing_country_is_neutral(self, analyzer):
        d = analyzer.analyze("ZZZ", sector="Technology", country="", industry="")
        assert d.classification == "Neutral"
        assert d.bonus == 0.0

    def test_case_insensitive_matching(self, analyzer):
        d = analyzer.analyze("ypf", sector="energy", country="ARGENTINA")
        assert d.classification == "Strong"

    def test_country_from_info_dict(self, analyzer):
        d = analyzer.analyze("ABCD", info={"sector": "Technology", "country": "United States"})
        assert d.classification == "Moderate"

    def test_disabled_config_is_always_neutral(self, data_file):
        cfg = TailwindConfig(enabled=False)
        a = TailwindAnalyzer(data_path=data_file, config=cfg)
        d = a.analyze("YPF", sector="Energy", country="Argentina")
        assert d.classification == "Neutral"
        assert d.bonus == 0.0

    def test_missing_data_file_all_neutral(self, tmp_path):
        invalidate_curated_cache()
        a = TailwindAnalyzer(data_path=tmp_path / "nope.json")
        d = a.analyze("YPF", sector="Energy", country="Argentina")
        assert d.classification == "Neutral"
        invalidate_curated_cache()

    def test_corrupt_data_file_all_neutral(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        invalidate_curated_cache()
        a = TailwindAnalyzer(data_path=p)
        d = a.analyze("YPF", sector="Energy", country="Argentina")
        assert d.classification == "Neutral"
        invalidate_curated_cache()


class TestShippedCuratedData:
    """The repo's real curated file must cover the motivating Argentina case."""

    def test_default_file_loads(self):
        invalidate_curated_cache()
        entries = load_curated_tailwinds()
        assert entries, "data/tailwinds/sector_country.json must have entries"
        invalidate_curated_cache()

    def test_ypf_is_strong_and_xom_neutral(self):
        invalidate_curated_cache()
        a = TailwindAnalyzer()
        ypf = a.analyze("YPF", sector="Energy", country="Argentina")
        xom = a.analyze("XOM", sector="Energy", country="United States")
        meli = a.analyze("MELI", sector="Consumer Cyclical", country="Uruguay")
        assert ypf.classification == "Strong" and ypf.bonus > 0
        assert xom.classification == "Neutral" and xom.bonus == 0.0
        assert meli.classification == "Neutral"
        invalidate_curated_cache()

    def test_curated_file_has_a_headwind_for_balance(self):
        invalidate_curated_cache()
        entries = load_curated_tailwinds()
        assert any(float(e.get("score", 0)) < 0 for e in entries)
        invalidate_curated_cache()


# ------------------------------------------------------------------ #
#  AI enrichment (graceful, cached, never changes the curated score)   #
# ------------------------------------------------------------------ #

class _FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


def _ai_cfg(enabled=True):
    return AIConfig(provider="claude", model="test-model", api_key="k", enabled=enabled)


class TestAIEnrichment:
    def test_ai_disabled_returns_base(self, analyzer):
        d = analyzer.analyze("YPF", sector="Energy", country="Argentina")
        out = analyzer.analyze_with_ai(d, "YPF", {}, _ai_cfg(enabled=False))
        assert out is d and not out.ai_available

    def test_neutral_never_calls_ai(self, analyzer):
        d = analyzer.analyze("XOM", sector="Energy", country="United States")
        with patch("analysis.moat.call_ai_api") as mock_call:
            out = analyzer.analyze_with_ai(d, "XOM", {}, _ai_cfg())
        mock_call.assert_not_called()
        assert out.classification == "Neutral"

    def test_api_failure_graceful(self, analyzer):
        d = analyzer.analyze("YPF", sector="Energy", country="Argentina")
        analyzer._cache = _FakeCache()
        with patch("analysis.moat.call_ai_api", side_effect=RuntimeError("boom")):
            out = analyzer.analyze_with_ai(d, "YPF", {}, _ai_cfg())
        # Curated base intact, no AI flag
        assert out.classification == "Strong"
        assert out.bonus == compute_tailwind_bonus(8.0)
        assert out.ai_available is False

    def test_success_populates_and_caches(self, analyzer):
        d = analyzer.analyze("YPF", sector="Energy", country="Argentina")
        analyzer._cache = _FakeCache()
        payload = json.dumps({
            "ai_reasoning": "Exposición directa a Vaca Muerta.",
            "factors": [{"factor": "export ramp", "why_relevant": "x",
                         "impact": "y", "effect_on_allocation_or_conviction": "z"}],
        })
        with patch("analysis.moat.call_ai_api", return_value=payload):
            out = analyzer.analyze_with_ai(d, "YPF", {"longName": "YPF SA"}, _ai_cfg())
        assert out.ai_available is True
        assert "Vaca Muerta" in out.ai_reasoning
        assert len(out.factors) == 1
        # Score/bonus never altered by AI
        assert out.tailwind_score == 8.0
        assert out.bonus == compute_tailwind_bonus(8.0)
        # Result cached
        assert any(k.startswith("tailwind_ai_YPF") for k in analyzer._cache.store)

    def test_cache_hit_skips_api(self, analyzer):
        d = analyzer.analyze("YPF", sector="Energy", country="Argentina")
        fake = _FakeCache()
        fake.store["tailwind_ai_YPF_claude_test-model"] = {
            "ai_reasoning": "cacheado", "factors": [],
        }
        analyzer._cache = fake
        with patch("analysis.moat.call_ai_api") as mock_call:
            out = analyzer.analyze_with_ai(d, "YPF", {}, _ai_cfg())
        mock_call.assert_not_called()
        assert out.ai_reasoning == "cacheado" and out.ai_available


# ------------------------------------------------------------------ #
#  Integration: FundamentalResult defaults + prompt injection          #
# ------------------------------------------------------------------ #

class TestFundamentalIntegration:
    def test_fundamental_result_defaults_are_neutral(self):
        from analysis.fundamental import FundamentalResult
        r = FundamentalResult(symbol="TEST")
        assert r.tailwind_score == 0.0
        assert r.tailwind_bonus == 0.0
        assert r.tailwind_classification == "Neutral"
        assert r.tailwind_detail is None

    def test_prompt_context_block_empty_for_neutral(self):
        from analysis.fundamental import FundamentalResult
        from analysis.prompts import _tailwind_context_block
        r = FundamentalResult(symbol="TEST")
        assert _tailwind_context_block(r) == ""

    def test_prompt_context_block_for_strong(self, analyzer):
        from analysis.fundamental import FundamentalResult
        from analysis.prompts import _tailwind_context_block
        d = analyzer.analyze("YPF", sector="Energy", country="Argentina")
        r = FundamentalResult(
            symbol="YPF", tailwind_classification=d.classification,
            tailwind_score=d.tailwind_score, tailwind_bonus=d.bonus, tailwind_detail=d,
        )
        block = _tailwind_context_block(r)
        assert "Cola de viento" in block
        assert "Vaca Muerta" in block
        assert "NO inventes" in block

    def test_enrichment_prompt_contract(self, analyzer):
        from analysis.prompts import sector_country_tailwind_prompt
        d = analyzer.analyze("YPF", sector="Energy", country="Argentina")
        p = sector_country_tailwind_prompt(d, "YPF", {"longName": "YPF SA", "country": "Argentina"})
        assert "ai_reasoning" in p and "factors" in p
        assert "NO inventes" in p
        assert "Vaca Muerta" in p


class TestStrategyRationale:
    def _tech(self):
        return SimpleNamespace(
            above_sma200=True, golden_cross=False, rsi_weekly=55.0,
            sma200_slope_pct=1.0, warnings=[],
        )

    def test_strong_tailwind_in_rationale(self, analyzer):
        from analysis.fundamental import FundamentalResult
        from analysis.strategy import Decision, RetirementStrategy
        d = analyzer.analyze("YPF", sector="Energy", country="Argentina")
        f = FundamentalResult(
            symbol="YPF", tailwind_classification="Strong", tailwind_detail=d,
        )
        dec = Decision(symbol="YPF")
        RetirementStrategy()._build_rationale(dec, f, self._tech())
        assert any("Cola de viento" in r for r in dec.rationale)

    def test_headwind_in_risks(self, analyzer):
        from analysis.fundamental import FundamentalResult
        from analysis.strategy import Decision, RetirementStrategy
        d = analyzer.analyze("XXAR", sector="Utilities", country="Argentina",
                             industry="Utilities - Regulated Electric")
        f = FundamentalResult(
            symbol="XXAR", tailwind_classification="Headwind", tailwind_detail=d,
        )
        dec = Decision(symbol="XXAR")
        RetirementStrategy()._build_rationale(dec, f, self._tech())
        assert any("Viento de frente" in r for r in dec.risks)

    def test_neutral_adds_nothing(self):
        from analysis.fundamental import FundamentalResult
        from analysis.strategy import Decision, RetirementStrategy
        f = FundamentalResult(symbol="MELI")
        dec = Decision(symbol="MELI")
        RetirementStrategy()._build_rationale(dec, f, self._tech())
        assert not any("viento" in r.lower() for r in dec.rationale + dec.risks)


# ------------------------------------------------------------------ #
#  Optimizer tilt + allocation fields                                  #
# ------------------------------------------------------------------ #

class TestOptimizerTailwind:
    def _ticker(self, symbol, tailwind=0.0, cls="Neutral"):
        return {
            "symbol": symbol, "adjusted_score": 65.0, "dividend_yield": 2.5,
            "moat_score": 8.0, "sector": "Technology",
            "tailwind_score": tailwind, "tailwind_classification": cls,
        }

    def test_expected_return_tilt_positive(self):
        from portfolio.optimizer import PortfolioOptimizer
        opt = PortfolioOptimizer("moderate")
        plain = self._ticker("AAA")
        windy = self._ticker("BBB", tailwind=8.0, cls="Strong")
        mu = opt._expected_returns([plain, windy])
        assert mu[1] > mu[0]
        # Tilt is small (≤1% annual) — never dominates
        assert (mu[1] - mu[0]) <= 0.01 + 1e-9

    def test_expected_return_tilt_negative_for_headwind(self):
        from portfolio.optimizer import PortfolioOptimizer
        opt = PortfolioOptimizer("moderate")
        plain = self._ticker("AAA")
        head = self._ticker("CCC", tailwind=-3.0, cls="Headwind")
        mu = opt._expected_returns([plain, head])
        assert mu[1] < mu[0]

    def test_missing_tailwind_keys_identical_to_zero(self):
        """Dicts without tailwind keys (pre-feature) behave exactly like score 0."""
        from portfolio.optimizer import PortfolioOptimizer
        opt = PortfolioOptimizer("conservative")
        legacy = {"symbol": "AAA", "adjusted_score": 65.0, "dividend_yield": 2.5,
                  "moat_score": 8.0, "sector": "Technology"}
        explicit = self._ticker("AAA", tailwind=0.0)
        mu = opt._expected_returns([legacy, explicit])
        assert mu[0] == pytest.approx(mu[1])

    def test_full_optimize_populates_tailwind_fields(self):
        """End-to-end: optimize() carries tailwind data into TickerAllocation."""
        import numpy as np
        import pandas as pd

        from portfolio.optimizer import PortfolioOptimizer

        def _fake_history(sym, period="2y", interval="1wk"):
            n = 110
            rng = np.random.default_rng(zlib.crc32(sym.encode()))  # stable across runs:
                # `hash()` is randomized per process (PYTHONHASHSEED), so seeding from it
                # regenerated different synthetic prices on every run and made this suite
                # non-reproducible — a green run proved nothing. Audit D4/D5.
            prices = 100.0 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
            dates = pd.date_range("2022-01-01", periods=n, freq="W")
            return pd.DataFrame({"close": prices}, index=dates)

        tickers = [self._ticker(f"XX{i:02d}") for i in range(8)]
        tickers.append(self._ticker("WIND", tailwind=8.0, cls="Strong"))
        with patch("portfolio.optimizer.get_history", side_effect=_fake_history):
            result = PortfolioOptimizer("aggressive").optimize(tickers)
        by_sym = {a.symbol: a for a in result.tickers}
        assert "WIND" in by_sym
        assert by_sym["WIND"].tailwind_classification == "Strong"
        assert by_sym["WIND"].tailwind_score == 8.0
        plains = [a for s, a in by_sym.items() if s != "WIND"]
        if plains:
            assert by_sym["WIND"].expected_return_pct >= max(p.expected_return_pct for p in plains)

    def test_ticker_allocation_defaults(self):
        from portfolio.optimizer import TickerAllocation
        a = TickerAllocation(
            symbol="X", weight_pct=10.0, expected_return_pct=8.0, volatility_pct=15.0,
            dividend_yield_pct=2.0, adjusted_score=70.0, moat_score=10.0, sector="Tech",
        )
        assert a.tailwind_score == 0.0
        assert a.tailwind_classification == "Neutral"


# ------------------------------------------------------------------ #
#  Plan snapshot capture + backward compat                             #
# ------------------------------------------------------------------ #

class TestPlanSnapshotTailwind:
    def _opt_result(self):
        def alloc(sym, w, tw=0.0, cls="Neutral"):
            return SimpleNamespace(
                symbol=sym, weight_pct=w, sector="Energy",
                dividend_yield_pct=1.0, adjusted_score=80.0,
                tailwind_score=tw, tailwind_classification=cls,
            )
        return SimpleNamespace(
            profile_name="Moderado",
            tickers=[alloc("YPF", 8.0, 8.0, "Strong"), alloc("XOM", 10.0)],
            expected_return_pct=8.0, volatility_pct=12.0, sharpe_ratio=0.5,
            dividend_yield_pct=2.0, adjusted_score_avg=75.0, moat_score_avg=10.0,
            max_drawdown_estimate_pct=18.0, sector_weights={"Energy": 18.0},
            profile_core_holdings=[], grok_core_holdings=[], ai_grok_narrative="",
        )

    def test_from_session_captures_material_tailwinds_only(self):
        from data.plan_store import PlanSnapshot
        snap = PlanSnapshot.from_session(name="x", opt_result=self._opt_result())
        by_sym = {a["symbol"]: a for a in snap.allocation}
        assert by_sym["YPF"]["tailwind_classification"] == "Strong"
        assert by_sym["YPF"]["tailwind_score"] == 8.0
        # Neutral entries stay byte-identical to pre-feature snapshots
        assert "tailwind_classification" not in by_sym["XOM"]
        assert "tailwind_score" not in by_sym["XOM"]

    def test_legacy_allocations_without_tailwind_attrs(self):
        from data.plan_store import PlanSnapshot
        legacy = SimpleNamespace(
            profile_name="Moderado",
            tickers=[SimpleNamespace(symbol="AAPL", weight_pct=40.0, sector="Tech",
                                     dividend_yield_pct=0.5, adjusted_score=80.0)],
            sector_weights={}, profile_core_holdings=[], grok_core_holdings=[],
            ai_grok_narrative="",
        )
        snap = PlanSnapshot.from_session(name="legacy", opt_result=legacy)
        assert "tailwind_classification" not in snap.allocation[0]

    def test_snapshot_json_roundtrip_with_tailwinds(self, tmp_path):
        from data.plan_store import PlanSnapshot, PlanStore
        store = PlanStore(path=tmp_path / "plans.json")
        snap = PlanSnapshot.from_session(name="tw", opt_result=self._opt_result())
        store.upsert(snap)
        loaded = store.get(snap.id)
        by_sym = {a["symbol"]: a for a in loaded.allocation}
        assert by_sym["YPF"]["tailwind_classification"] == "Strong"

    def test_plan_narrative_prompt_mentions_tailwinds(self):
        from analysis.prompts import plan_level_narrative_prompt
        p = plan_level_narrative_prompt(
            plan_name="P", profile_name="Moderado", personal=None,
            metrics={}, core_holdings=[],
            allocation=[{"symbol": "YPF", "weight_pct": 8.0,
                         "tailwind_classification": "Strong", "tailwind_score": 8.0}],
            sector_weights={}, goals=[], mc_summary=None,
        )
        assert "COLAS DE VIENTO" in p
        assert "YPF" in p and "Strong" in p

    def test_plan_narrative_prompt_without_tailwinds(self):
        from analysis.prompts import plan_level_narrative_prompt
        p = plan_level_narrative_prompt(
            plan_name="P", profile_name="Moderado", personal=None,
            metrics={}, core_holdings=[],
            allocation=[{"symbol": "AAPL", "weight_pct": 40.0}],
            sector_weights={}, goals=[], mc_summary=None,
        )
        assert "sin colas de viento estructurales materiales" in p
