"""
Tests for analysis/prompts.py — centralized LLM prompt library.

Verifies that all four prompt functions:
  1. Return non-empty strings
  2. Use the Grok voice convention ("Eres Grok, construido por xAI")
  3. Include every required JSON field name in the prompt text
  4. Produce syntactically valid JSON template (parseable field structure)

No network calls, no LLM calls — pure string/structure tests.
"""

from __future__ import annotations

import json
import re

import pytest

from analysis.fundamental import FundamentalResult
from analysis.moat import MoatDetail
from analysis.prompts import (
    crypto_decision_prompt,
    crypto_moat_prompt,
    equity_decision_prompt,
    equity_moat_prompt,
    plan_level_narrative_prompt,
    portfolio_optimizer_advice_prompt,
)
from analysis.technical import TechnicalResult

# ------------------------------------------------------------------ #
#  Helpers — build minimal but realistic stub objects                  #
# ------------------------------------------------------------------ #

def _equity_fund(symbol: str = "AAPL") -> FundamentalResult:
    """Minimal FundamentalResult with all float fields set to avoid format errors."""
    r = FundamentalResult(symbol=symbol)
    r.company_name = "Apple Inc."
    r.sector = "Technology"
    r.current_price = 200.0
    r.market_cap = 3_000_000_000_000.0
    r.profitability_score = 20.0
    r.health_score = 15.0
    r.valuation_score = 18.0
    r.growth_score = 12.0
    r.dividend_score = 5.0
    r.total_score = 70.0
    r.adjusted_score = 72.0
    r.moat_score = 14.0
    r.moat_classification = "Wide"
    r.moat_detail = None
    r.roe = 35.0
    r.roic = 25.0
    r.net_margin = 25.0
    r.gross_margin = 44.0
    r.debt_equity = 1.5
    r.current_ratio = 1.1
    r.interest_coverage = 20.0
    r.pe_ratio = 28.0
    r.peg_ratio = 2.1
    r.ev_ebitda = 22.0
    r.pb_ratio = 45.0
    r.fcf_yield = 3.5
    r.dividend_yield = 0.5
    r.payout_ratio = 15.0
    r.margin_of_safety_pct = -5.0
    r.graham_value = 180.0
    r.revenue_cagr_5y = 8.0
    r.eps_cagr_5y = 12.0
    r.consistency_score = 10.0
    r.piotroski_score = 7
    r.piotroski_bonus = 5.0
    return r


def _tech(symbol: str = "AAPL") -> TechnicalResult:
    """TechnicalResult with sensible defaults (all numeric fields set)."""
    t = TechnicalResult(symbol=symbol)
    t.signal = "BULLISH"
    t.signal_strength = 60       # int — matches format spec :+d
    t.current_price = 200.0
    t.above_sma50 = True
    t.above_sma100 = True
    t.above_sma200 = True
    t.sma200_slope_pct = 1.5
    t.rsi_weekly = 58.0
    t.macd_bullish = True
    t.adx = 28.0
    t.atr_pct = 1.2
    t.near_bb_upper = False
    t.near_bb_lower = False
    t.volume_trend = "rising"
    t.price_vs_52w_high_pct = -5.0
    t.price_vs_52w_low_pct = 30.0
    return t


def _moat_quant(symbol: str = "AAPL") -> MoatDetail:
    """MoatDetail with all quantitative sub-scores set."""
    m = MoatDetail()
    m.gross_margin_level = 1.5
    m.gross_margin_stability = 1.5
    m.roic_sustained = 2.0
    m.revenue_defensiveness = 1.5
    m.fcf_conversion = 1.5
    m.fcf_margin = 2.0
    m.quant_total = 10.0
    return m


def _crypto_fund(symbol: str = "BTC-USD") -> FundamentalResult:
    """Minimal FundamentalResult with is_crypto=True."""
    r = FundamentalResult(symbol=symbol)
    r.is_crypto = True
    r.company_name = "Bitcoin"
    r.sector = "Crypto / Digital Asset"
    r.current_price = 100_000.0
    r.market_cap = 2_000_000_000_000.0
    r.adjusted_score = 55.0
    r.notes = {
        "crypto_vol": "Volatilidad anualizada (52s): 65.0%",
        "crypto_dd": "Drawdown máximo histórico: -77.0%",
        "crypto_cagr": "CAGR precio 4 años: 45.0%",
        "crypto_halving": "Ciclo halving: post-halving (400d desde último / 1050d al próximo)",
    }
    r.warnings = []
    return r


def _crypto_info() -> dict:
    return {
        "currentPrice": 100_000.0,
        "marketCap": 2_000_000_000_000,
        "circulatingSupply": 19_700_000,
        "maxSupply": 21_000_000,
        "fiftyTwoWeekHigh": 110_000.0,
        "fiftyTwoWeekLow": 48_000.0,
        "volume": 25_000_000_000,
    }


def _crypto_metrics() -> dict:
    return {
        "annualized_volatility_pct": 65.0,
        "max_drawdown_pct": -77.0,
        "cagr_4y_pct": 45.0,
        "supply_scarcity_pct": 93.8,
        "halving_cycle_position": "post-halving",
        "days_since_last_halving": 400,
        "days_to_next_halving": 1050,
    }


# ------------------------------------------------------------------ #
#  1. equity_moat_prompt                                               #
# ------------------------------------------------------------------ #

class TestEquityMoatPrompt:
    def _prompt(self) -> str:
        info = {
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "country": "United States",
            "longBusinessSummary": "Apple Inc. designs, manufactures and markets smartphones.",
        }
        return equity_moat_prompt(_moat_quant(), "AAPL", info)

    def test_returns_nonempty_string(self):
        assert isinstance(self._prompt(), str)
        assert len(self._prompt()) > 200

    def test_uses_grok_voice(self):
        """All prompts must open with the Grok voice convention."""
        assert "Eres Grok, construido por xAI" in self._prompt()

    def test_contains_required_json_fields(self):
        prompt = self._prompt()
        required = [
            "brand_strength",
            "network_effects",
            "switching_costs",
            "regulatory_ip",
            "moat_durability_years",
            "recommended_max_allocation_conservative",
            "reasoning",
            "macro_factors",
        ]
        for field in required:
            assert field in prompt, f"Missing JSON field in equity_moat_prompt: {field}"

    def test_json_template_is_parseable(self):
        """The JSON schema block in the prompt must be parseable after replacing 0.0 / int placeholders."""
        prompt = self._prompt()
        # Extract the JSON block (between first {{ and last }})
        match = re.search(r"\{[\s\S]*\}", prompt)
        assert match, "No JSON block found in equity_moat_prompt"
        raw = match.group().strip()
        # Replace Python f-string escaped braces
        try:
            data = json.loads(raw)
            assert "brand_strength" in data
        except json.JSONDecodeError as e:
            pytest.fail(f"JSON block in equity_moat_prompt is not valid JSON: {e}\n\nBlock: {raw[:300]}")


# ------------------------------------------------------------------ #
#  2. equity_decision_prompt                                           #
# ------------------------------------------------------------------ #

class TestEquityDecisionPrompt:
    def _prompt(self) -> str:
        return equity_decision_prompt(_equity_fund(), _tech())

    def test_returns_nonempty_string(self):
        assert len(self._prompt()) > 200

    def test_uses_grok_voice(self):
        assert "Eres Grok, construido por xAI" in self._prompt()

    def test_contains_required_json_fields(self):
        prompt = self._prompt()
        required = [
            "action",
            "confidence",
            "rationale",
            "risks",
            "recommended_max_allocation_conservative",
            "reasoning",
            "macro_factors",
        ]
        for field in required:
            assert field in prompt, f"Missing JSON field in equity_decision_prompt: {field}"

    def test_structural_macro_instructions_present(self):
        """Structural improvement: prompt must instruct on explicit macro_factors list, zero-allowed, and data anchoring."""
        prompt = self._prompt()
        low = prompt.lower()
        assert "macro_factors" in prompt
        assert "0-2" in prompt or "0-2 factores" in low or "macro_factors" in low
        assert "ningún factor" in low or "ningun factor" in low or "vacío" in low or "[]" in prompt  # permission for zero
        assert "números concretos" in low or "datos duros" in low or "con los datos" in low  # anchoring

    def test_json_template_is_parseable(self):
        prompt = self._prompt()
        match = re.search(r"\{[\s\S]*\}", prompt)
        assert match, "No JSON block found"
        raw = match.group().strip()
        try:
            data = json.loads(raw)
            assert "action" in data
        except json.JSONDecodeError as e:
            pytest.fail(f"JSON block in equity_decision_prompt is not valid: {e}")

    def test_argentina_adr_adds_country_context(self):
        """Argentine ADRs (YPF, GGAL, etc.) must inject country risk context."""
        fund = _equity_fund("YPF")
        prompt = equity_decision_prompt(fund, _tech("YPF"))
        assert "Argentina" in prompt or "emergente" in prompt.lower()

    def test_includes_confidence_justification_instruction(self):
        """Prompt must instruct the model to justify the confidence level within reasoning."""
        prompt = self._prompt()
        low = prompt.lower()
        assert "justif" in low or "elegiste" in low or "elegí" in low
        assert "high" in low and "medium" in low and "low" in low


# ------------------------------------------------------------------ #
#  3. crypto_moat_prompt                                               #
# ------------------------------------------------------------------ #

class TestCryptoMoatPrompt:
    def _prompt(self) -> str:
        return crypto_moat_prompt("BTC-USD", _crypto_info(), _crypto_metrics())

    def test_returns_nonempty_string(self):
        assert len(self._prompt()) > 200

    def test_uses_grok_voice(self):
        assert "Eres Grok, construido por xAI" in self._prompt()

    def test_contains_required_json_fields(self):
        prompt = self._prompt()
        required = [
            "network_adoption",
            "monetary_scarcity",
            "security_decentralization",
            "institutional_regulatory",
            "tech_resilience",
            "moat_durability_years",
            "recommended_max_allocation_conservative",
            "retirement_risk_summary",
            "reasoning",
            "macro_factors",
        ]
        for field in required:
            assert field in prompt, f"Missing JSON field in crypto_moat_prompt: {field}"

    def test_json_template_is_parseable(self):
        prompt = self._prompt()
        match = re.search(r"\{[\s\S]*\}", prompt)
        assert match, "No JSON block found"
        raw = match.group().strip()
        try:
            data = json.loads(raw)
            assert "network_adoption" in data
        except json.JSONDecodeError as e:
            pytest.fail(f"JSON block in crypto_moat_prompt is not valid: {e}")

    def test_mentions_retirement_context(self):
        """Crypto moat prompt must frame analysis in retirement portfolio context."""
        prompt = self._prompt()
        assert "retiro" in prompt.lower() or "jubilaci" in prompt.lower()


# ------------------------------------------------------------------ #
#  4. crypto_decision_prompt                                           #
# ------------------------------------------------------------------ #

class TestCryptoDecisionPrompt:
    def _prompt(self) -> str:
        return crypto_decision_prompt(_crypto_fund(), _tech("BTC-USD"))

    def test_returns_nonempty_string(self):
        assert len(self._prompt()) > 200

    def test_uses_grok_voice(self):
        assert "Eres Grok, construido por xAI" in self._prompt()

    def test_contains_required_json_fields(self):
        prompt = self._prompt()
        required = [
            "action",
            "confidence",
            "rationale",
            "risks",
            "recommended_max_allocation_conservative",
            "reasoning",
            "macro_factors",
        ]
        for field in required:
            assert field in prompt, f"Missing JSON field in crypto_decision_prompt: {field}"

    def test_json_template_is_parseable(self):
        prompt = self._prompt()
        match = re.search(r"\{[\s\S]*\}", prompt)
        assert match, "No JSON block found"
        raw = match.group().strip()
        try:
            data = json.loads(raw)
            assert "action" in data
        except json.JSONDecodeError as e:
            pytest.fail(f"JSON block in crypto_decision_prompt is not valid: {e}")

    def test_includes_confidence_justification_instruction(self):
        """Prompt must instruct the model to justify the confidence level within reasoning."""
        prompt = self._prompt()
        low = prompt.lower()
        assert "justif" in low or "elegiste" in low or "elegí" in low
        assert "high" in low and "medium" in low and "low" in low


# ------------------------------------------------------------------ #
#  5. portfolio_optimizer_advice_prompt (Grok voice + human core)      #
# ------------------------------------------------------------------ #

def _sample_holdings(n: int = 18) -> list[dict]:
    """Minimal realistic holdings list for optimizer advice prompt tests."""
    syms = ["AAPL", "MSFT", "GOOGL", "AMZN", "JPM", "V", "JNJ", "PG", "XOM", "HD",
            "MELI", "GGAL", "BTC-USD"] + [f"T{i}" for i in range(n - 13)]
    out = []
    for i, s in enumerate(syms[:n]):
        w = round(100.0 / n, 1)
        out.append({
            "symbol": s,
            "weight_pct": w,
            "adjusted_score": 65.0 + (i % 5),
            "moat_score": 8.0 + (i % 3) * 0.5,
            "dividend_yield_pct": 2.5 + (i % 4) * 0.3,
            "expected_return_pct": 9.0 + (i % 3),
            "volatility_pct": 14.0 + (i % 4),
            "sector": ["Technology", "Financials", "Healthcare", "Consumer Staples", "Energy", "Industrials"][i % 6],
            "is_ars": s in ("MELI", "GGAL"),
        })
    return out


class TestPortfolioOptimizerAdvicePrompt:
    def _prompt(self) -> str:
        return portfolio_optimizer_advice_prompt(
            profile_name="Conservador",
            holdings=_sample_holdings(18),
            expected_return_pct=9.2,
            volatility_pct=13.8,
            sharpe=0.72,
            dividend_yield_pct=3.8,
            moat_avg=9.1,
            num_positions=18,
            sector_weights={"Technology": 28.0, "Financials": 18.0, "Healthcare": 15.0, "Energy": 12.0},
            max_position_pct=8.0,
            min_positions=10,
            max_volatility_pct=12.0,
            min_dividend_yield_pct=3.5,
            max_crypto_pct=3.0,
            goal_explanation="Glide Path activo por meta de corto plazo.",
            rebalance_rationale="Anual — perfil conservador.",
            warnings=["Alta concentración tech."],
            holdings_note="",
        )

    def test_returns_nonempty_string(self):
        p = self._prompt()
        assert isinstance(p, str)
        assert len(p) > 300

    def test_uses_grok_voice(self):
        assert "Eres Grok, construido por xAI" in self._prompt()

    def test_contains_required_json_fields(self):
        p = self._prompt()
        required = [
            "narrative",
            "recommended_max_human_positions",
            "core_holdings",
            "dropped_tickers",
            "human_review_tips",
            "overall_assessment",
            "macro_factors",
        ]
        for field in required:
            assert field in p, f"Missing JSON field in portfolio_optimizer_advice_prompt: {field}"

    def test_json_template_is_parseable(self):
        p = self._prompt()
        match = re.search(r"\{[\s\S]*\}", p)
        assert match, "No JSON block found in portfolio_optimizer_advice_prompt"
        raw = match.group().strip()
        try:
            data = json.loads(raw)
            assert "narrative" in data
            assert "recommended_max_human_positions" in data
        except json.JSONDecodeError as e:
            pytest.fail(f"JSON block in portfolio_optimizer_advice_prompt is not valid: {e}")

    def test_mentions_human_manageable_concentration(self):
        p = self._prompt()
        low = p.lower()
        assert "humano" in low or "revisar" in low or "ajustar" in low or "núcleo" in low or "concentrad" in low
        # Grok must be asked to pick a smaller number than the input 18
        assert "recommended_max_human_positions" in p

    def test_27_positions_does_not_block_and_supports_core(self):
        """For the user's real minimum (~27), we must still produce voice + core recommendation
        (via truncation + updated prompt language), not the old 'too large, use smaller universe' block."""
        p27 = portfolio_optimizer_advice_prompt(
            profile_name="Agresivo",
            holdings=_sample_holdings(27),
            expected_return_pct=10.5,
            volatility_pct=15.0,
            sharpe=0.65,
            dividend_yield_pct=2.8,
            moat_avg=8.5,
            num_positions=27,
            sector_weights={"Technology": 35.0, "Financials": 20.0},
            max_position_pct=12.0,
            min_positions=8,
            max_volatility_pct=18.0,
            min_dividend_yield_pct=2.0,
            max_crypto_pct=5.0,
            goal_explanation="",
            rebalance_rationale="Trimestral",
            warnings=[],
            holdings_note=" (top 15 de 27 total)",
        )
        low = p27.lower()
        # Must not contain the old blocking message
        assert "grok no genera explicación detallada ni recomendación de núcleo para carteras tan grandes" not in low
        assert "usá un universo más chico" not in low
        # Must still mention human/review/core and the total 27
        assert "humano" in low or "revisar" in low or "núcleo" in low
        assert "27" in p27
        # The JSON contract fields must still be present in the template
        assert "recommended_max_human_positions" in p27
        assert "core_holdings" in p27
        # Note must be injected
        assert "top 15 de 27" in p27 or "se muestran solo las 15" in p27


# ------------------------------------------------------------------ #
#  Fase D — plan_level_narrative_prompt                                #
# ------------------------------------------------------------------ #

def _plan_prompt(**overrides):
    kwargs = dict(
        plan_name="Retiro 2045",
        profile_name="Moderado",
        personal={"age": 40, "retirement_age": 65, "primary_horizon_years": 25,
                  "current_capital": 200_000, "monthly_savings": 1_500, "primary_goal_type": "retiro"},
        metrics={"expected_return_pct": 8.5, "volatility_pct": 12.0, "sharpe_ratio": 0.55,
                 "dividend_yield_pct": 2.4, "adjusted_score_avg": 75, "max_drawdown_estimate_pct": 18},
        core_holdings=[{"symbol": "AAPL", "suggested_weight_pct": 40, "why": "moat wide"}],
        allocation=[{"symbol": "AAPL", "weight_pct": 40}, {"symbol": "KO", "weight_pct": 60}],
        sector_weights={"Tech": 40, "Staples": 60},
        goals=[{"name": "Casa", "target_amount_today": 100_000, "horizon_years": 5}],
        mc_summary={"horizon_years": 25, "initial_value": 200_000, "median_terminal": 900_000,
                    "p10_terminal": 300_000, "p90_terminal": 2_000_000,
                    "prob_ruin_pct": 2.0, "prob_target_pct": 70.0},
    )
    kwargs.update(overrides)
    return plan_level_narrative_prompt(**kwargs)


class TestPlanLevelNarrativePrompt:
    def test_returns_nonempty_with_required_fields(self):
        p = _plan_prompt()
        assert isinstance(p, str) and len(p) > 200
        # JSON contract fields present in the template
        assert "narrative" in p
        assert "macro_risks" in p
        # Plan + profile context woven in
        assert "Retiro 2045" in p
        assert "Moderado" in p

    def test_spanish_and_conservative_voice(self):
        p = _plan_prompt().lower()
        assert "español" in p
        assert "no se arruine" in p or "conservador" in p

    def test_personal_and_goals_surfaced(self):
        p = _plan_prompt()
        assert "Casa" in p          # goal name
        assert "200,000" in p       # capital formatted

    def test_handles_missing_personal_and_mc(self):
        p = _plan_prompt(personal=None, mc_summary=None, goals=[])
        assert "Perfil personal no definido" in p
        assert "Sin simulación Monte Carlo" in p

    def test_refresh_block_included_when_provided(self):
        refreshed = {"summary": {"weighted_delta_pct": 2.0, "gainers": 1, "losers": 1, "avg_score_then": 75}}
        p = _plan_prompt(refreshed=refreshed)
        assert "+2.0%" in p

    # --- Fase H.1: decumulation narrative ---

    def test_accumulation_block_when_no_strategy(self):
        p = _plan_prompt()
        assert "ESTRATEGIA DE RETIRO" in p
        assert "fase de ACUMULACIÓN" in p

    def test_guardrails_strategy_described_with_metrics(self):
        mc = {"horizon_years": 30, "initial_value": 1_000_000, "median_terminal": 800_000,
              "p10_terminal": 100_000, "p90_terminal": 2_000_000, "prob_ruin_pct": 10.0,
              "prob_target_pct": 0.0, "prob_sustain_real_pct": 82.0, "prob_legacy_pct": 55.0,
              "median_legacy": 120_000, "expected_depletion_year": 27.0, "longevity_years": 30}
        p = _plan_prompt(
            mc_summary=mc,
            withdrawal_strategy={"kind": "guardrails", "pct": 0.04, "label": "Guardrails 4.0%"},
        )
        assert "GUARDRAILS" in p
        assert "82%" in p              # prob sustain surfaced
        assert "dure 30 años" in p
        # Narrative guidance asks for the retirement-income bullet + sequence risk.
        assert "¿Cuánto dura tu ingreso?" in p
        assert "secuencia de retornos" in p

    def test_fixed_real_strategy_described(self):
        p = _plan_prompt(
            withdrawal_strategy={"kind": "fixed_real", "annual_amount": 40_000},
        )
        assert "RETIRO FIJO REAL" in p
        assert "40,000" in p

    def test_strategy_without_metrics_notes_absence(self):
        p = _plan_prompt(
            mc_summary={"horizon_years": 30, "initial_value": 100_000},
            withdrawal_strategy={"kind": "constant_pct", "pct": 0.045},
        )
        assert "% CONSTANTE" in p
        assert "sin métricas de decumulación" in p


# ------------------------------------------------------------------ #
#  Fase D — AIAnalyzer.generate_plan_narrative (parse + fallback)      #
# ------------------------------------------------------------------ #

class TestGeneratePlanNarrative:
    def _analyzer(self, raw_or_exc):
        from types import SimpleNamespace

        from analysis.ai_analyzer import AIAnalyzer

        a = AIAnalyzer(SimpleNamespace(provider="claude", model="x", api_key="k", enabled=True))
        if isinstance(raw_or_exc, Exception):
            def _boom(_p, max_tokens=None):
                raise raw_or_exc
            a._call_api = _boom
        else:
            a._call_api = lambda _p, max_tokens=None: raw_or_exc
        return a

    def _snap(self):
        from types import SimpleNamespace
        return SimpleNamespace(
            name="Retiro 2045", profile_name="Moderado", personal=None,
            metrics={}, core_holdings=[], allocation=[], sector_weights={},
            goals=[], mc_summary=None,
        )

    def test_parses_narrative_and_caps_macro_at_two(self):
        raw = (
            '{"narrative": "**Resumen** Plan sólido pero con riesgos.", '
            '"macro_risks": ['
            '{"factor": "Tasas", "why": "growth sensible", "severity": "MEDIA"}, '
            '{"factor": "Inflación", "why": "erosiona retiros", "severity": "alta"}, '
            '{"factor": "Extra", "why": "n/a", "severity": "baja"}]}'
        )
        out = self._analyzer(raw).generate_plan_narrative(self._snap())
        assert out["narrative"].startswith("**Resumen**")
        assert len(out["macro_risks"]) == 2            # capped
        assert out["macro_risks"][0]["severity"] == "media"  # normalised to lowercase

    def test_drops_malformed_macro_entries(self):
        raw = '{"narrative": "ok", "macro_risks": [{"why": "no factor"}, "garbage"]}'
        out = self._analyzer(raw).generate_plan_narrative(self._snap())
        assert out["macro_risks"] == []

    def test_fallback_on_api_error(self):
        out = self._analyzer(RuntimeError("rate limit")).generate_plan_narrative(self._snap())
        assert "No se pudo generar" in out["narrative"]
        assert out["macro_risks"] == []

    def test_non_json_response_becomes_narrative(self):
        out = self._analyzer("Una explicación en prosa sin JSON.").generate_plan_narrative(self._snap())
        assert "prosa" in out["narrative"]
        assert out["macro_risks"] == []

    def test_withdrawal_strategy_wired_into_prompt(self):
        """Fase H.1: the snapshot's withdrawal_strategy reaches the prompt."""
        captured = {}
        a = self._analyzer('{"narrative": "ok", "macro_risks": []}')
        orig = a._call_api
        a._call_api = lambda p, max_tokens=None: captured.setdefault("prompt", p) or orig(p)
        snap = self._snap()
        snap.withdrawal_strategy = {"kind": "guardrails", "pct": 0.04}
        a.generate_plan_narrative(snap)
        assert "GUARDRAILS" in captured["prompt"]
