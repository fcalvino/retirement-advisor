"""Tests for the data-quality transparency layer (Fase E)."""

from __future__ import annotations

from analysis.fundamental import (
    _QUALITY_KEY_FIELDS,
    FundamentalResult,
    compute_data_quality,
)
from config import DataQualityConfig

_CFG = DataQualityConfig()  # explicit instance — tests don't depend on env overrides


def _full_result(**overrides) -> FundamentalResult:
    """Equity result with every key metric populated (level should be 'good')."""
    r = FundamentalResult(symbol="AAPL", sector="Technology", current_price=180.0)
    for f in _QUALITY_KEY_FIELDS:
        setattr(r, f, 1.0)
    for k, v in overrides.items():
        setattr(r, k, v)
    return r


def _blank(fields: int) -> FundamentalResult:
    """Equity result with the first *fields* key metrics missing."""
    r = _full_result()
    for f in _QUALITY_KEY_FIELDS[:fields]:
        setattr(r, f, None)
    return r


# ------------------------------------------------------------------ #
#  Completeness levels                                                #
# ------------------------------------------------------------------ #

def test_all_fields_present_is_good():
    dq = compute_data_quality(_full_result(), config=_CFG)
    assert dq["level"] == "good"
    assert dq["missing_fields"] == []
    assert dq["n_missing"] == 0
    assert dq["n_checked"] == len(_QUALITY_KEY_FIELDS)
    assert dq["warnings"] == []


def test_few_missing_fields_still_good():
    dq = compute_data_quality(_blank(_CFG.partial_missing_fields - 1), config=_CFG)
    assert dq["level"] == "good"


def test_partial_threshold():
    dq = compute_data_quality(_blank(_CFG.partial_missing_fields), config=_CFG)
    assert dq["level"] == "partial"
    assert dq["n_missing"] == _CFG.partial_missing_fields
    assert dq["warnings"]


def test_poor_threshold():
    dq = compute_data_quality(_blank(_CFG.poor_missing_fields), config=_CFG)
    assert dq["level"] == "poor"


def test_missing_financial_statements_is_poor_even_with_metrics():
    dq = compute_data_quality(_full_result(), has_financials=False, config=_CFG)
    assert dq["level"] == "poor"
    assert any("financieros" in w for w in dq["warnings"])


def test_missing_dividend_yield_does_not_count():
    """None dividend_yield is legitimate for growth stocks — never penalized."""
    r = _full_result(dividend_yield=None)
    dq = compute_data_quality(r, config=_CFG)
    assert dq["level"] == "good"
    assert "dividend_yield" not in dq["missing_fields"]


# ------------------------------------------------------------------ #
#  Freshness / staleness                                              #
# ------------------------------------------------------------------ #

def test_fresh_cache_not_stale():
    dq = compute_data_quality(_full_result(), freshness_hours=2.0, config=_CFG)
    assert dq["stale"] is False
    assert dq["freshness_hours"] == 2.0


def test_old_cache_flags_stale_but_keeps_level():
    dq = compute_data_quality(
        _full_result(), freshness_hours=_CFG.stale_warning_hours + 1, config=_CFG
    )
    assert dq["stale"] is True
    assert dq["level"] == "good"          # staleness is an independent dimension
    assert any("cacheados" in w for w in dq["warnings"])


def test_unknown_freshness_is_none_and_not_stale():
    dq = compute_data_quality(_full_result(), freshness_hours=None, config=_CFG)
    assert dq["freshness_hours"] is None
    assert dq["stale"] is False


# ------------------------------------------------------------------ #
#  Non-fundamental assets (crypto / ETF / index)                      #
# ------------------------------------------------------------------ #

def test_crypto_with_price_is_good():
    r = FundamentalResult(symbol="BTC-USD", sector="Crypto", is_crypto=True, current_price=60_000.0)
    dq = compute_data_quality(r, config=_CFG)
    assert dq["level"] == "good"
    assert dq["missing_fields"] == []


def test_etf_without_price_is_poor():
    r = FundamentalResult(symbol="SPY", sector="Index", current_price=0.0)
    dq = compute_data_quality(r, config=_CFG)
    assert dq["level"] == "poor"
    assert dq["missing_fields"] == ["current_price"]
