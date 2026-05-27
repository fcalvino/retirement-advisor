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
from unittest.mock import MagicMock

import pytest

from analysis.fundamental import FundamentalResult
from analysis.moat import MoatDetail
from analysis.prompts import (
    crypto_decision_prompt,
    crypto_moat_prompt,
    equity_decision_prompt,
    equity_moat_prompt,
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
        ]
        for field in required:
            assert field in prompt, f"Missing JSON field in equity_decision_prompt: {field}"

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
