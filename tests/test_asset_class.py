"""Asset-class classification (audit item 01).

The defect these lock down was measured on the US Quality universe (85 tickers,
2026-08-17): the six pooled vehicles in it — SPY, QQQ, VTI, BND, SCHD, VGT —
scored 22–25 on the equity scorer and were the six worst of the universe, each
carrying a SELL signal. They have no financial statements, so that score was not
a harsh verdict, it was a category error.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.asset_class import (
    CRYPTO,
    EQUITY,
    FUND,
    asset_class_label,
    classify_asset,
    classify_result,
    is_fundamentally_scorable,
    split_by_scorability,
)
from config import ASSET_CLASS, AssetClassConfig

ROOT = Path(__file__).resolve().parents[1]
SCREENER = (ROOT / "dashboard" / "pages" / "1_Screener.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  quoteType is authoritative                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "quote_type,expected",
    [
        ("ETF", FUND),
        ("etf", FUND),
        ("MUTUALFUND", FUND),
        ("INDEX", FUND),
        ("MONEYMARKET", FUND),
        ("CRYPTOCURRENCY", CRYPTO),
        ("EQUITY", EQUITY),
    ],
)
def test_quote_type_decides(quote_type, expected):
    assert classify_asset("XXXX", quote_type=quote_type) == expected


def test_quote_type_beats_a_curated_list_that_has_not_caught_up():
    """The curated list will always lag; quoteType must not depend on it.

    VGT and SCHD were the original case — ETFs missing from SECTOR_MAP that
    resolved to sector "Unknown" and got scored as companies. They have since
    been added (audit item 23), so the guarantee is retested with a symbol the
    list does not know, which is the situation that recurs every time a universe
    gains an ETF.
    """
    etf_list = {s.upper() for s in __import__("config").SECTOR_MAP["ETF"]}
    assert "IJR" not in etf_list          # not curated
    assert classify_asset("IJR", quote_type="ETF") == FUND
    # And the ones that burned us are covered by both paths now.
    for sym in ("VGT", "SCHD"):
        assert sym in etf_list
        assert classify_asset(sym) == FUND
        assert classify_asset(sym, quote_type="ETF") == FUND


# --------------------------------------------------------------------------- #
#  Fallbacks when the feed gives nothing                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("symbol", ["SPY", "QQQ", "VTI", "BND"])
def test_curated_etf_list_still_works_without_quote_type(symbol):
    assert classify_asset(symbol) == FUND


def test_crypto_recognised_by_symbol_and_by_flag():
    assert classify_asset("BTC-USD") == CRYPTO
    assert classify_asset("ETH-USD") == CRYPTO
    assert classify_asset("ANYTHING", is_crypto=True) == CRYPTO


def test_sector_is_the_last_resort():
    assert classify_asset("ZZZZ", sector="Index") == FUND
    assert classify_asset("ZZZZ", sector="Crypto / Digital Asset") == CRYPTO
    assert classify_asset("ZZZZ", sector="Technology") == EQUITY


def test_unknown_symbol_defaults_to_equity():
    """The default must stay equity so nothing silently leaves the ranking."""
    assert classify_asset("ZZZZ") == EQUITY
    assert classify_asset("") == EQUITY
    assert classify_asset("ZZZZ", quote_type="", sector="Unknown") == EQUITY


def test_real_companies_are_never_reclassified():
    for sym in ("AAPL", "MSFT", "GOOGL", "JPM", "XOM", "YPF"):
        assert classify_asset(sym, quote_type="EQUITY", sector="Technology") == EQUITY
        assert classify_asset(sym) == EQUITY


# --------------------------------------------------------------------------- #
#  Scorability                                                                #
# --------------------------------------------------------------------------- #


def test_only_equities_are_fundamentally_scorable():
    assert is_fundamentally_scorable(EQUITY) is True
    assert is_fundamentally_scorable(FUND) is False
    assert is_fundamentally_scorable(CRYPTO) is False
    # Unknown/blank must not be treated as scorable by accident.
    assert is_fundamentally_scorable("") is False


def test_scorability_reads_config_not_a_literal():
    cfg = AssetClassConfig(scorable_classes=("equity", "fund"))
    assert is_fundamentally_scorable(FUND, config=cfg) is True
    assert is_fundamentally_scorable(FUND) is False   # singleton unchanged


def test_labels_are_spanish_and_table_sized():
    assert asset_class_label(EQUITY) == "Acción"
    assert asset_class_label(FUND) == "Fondo / ETF"
    assert asset_class_label(CRYPTO) == "Cripto"
    for cls in (EQUITY, FUND, CRYPTO):
        assert len(asset_class_label(cls)) <= 14


# --------------------------------------------------------------------------- #
#  Result-shaped input + the split the Screener performs                      #
# --------------------------------------------------------------------------- #


def test_classify_result_reads_a_fundamental_result():
    equity = SimpleNamespace(symbol="AAPL", sector="Technology", is_crypto=False)
    fund = SimpleNamespace(symbol="SPY", sector="Index", is_crypto=False)
    coin = SimpleNamespace(symbol="BTC-USD", sector="Crypto / Digital Asset", is_crypto=True)
    assert classify_result(equity) == EQUITY
    assert classify_result(fund) == FUND
    assert classify_result(coin) == CRYPTO


def test_split_by_scorability_preserves_order_and_separates_the_measured_six():
    rows = [
        {"Ticker": "INTU", "Clase": EQUITY},
        {"Ticker": "SPY", "Clase": FUND},
        {"Ticker": "GOOGL", "Clase": EQUITY},
        {"Ticker": "BND", "Clase": FUND},
        {"Ticker": "BTC-USD", "Clase": CRYPTO},
        {"Ticker": "VGT", "Clase": FUND},
        {"Ticker": "SCHD", "Clase": FUND},
        {"Ticker": "QQQ", "Clase": FUND},
        {"Ticker": "VTI", "Clase": FUND},
    ]
    scorable, other = split_by_scorability(rows)
    assert [r["Ticker"] for r in scorable] == ["INTU", "GOOGL"]
    # The exact six that shipped as the worst of the universe, plus the coin.
    assert {r["Ticker"] for r in other} == {
        "SPY", "QQQ", "VTI", "BND", "SCHD", "VGT", "BTC-USD",
    }


def test_rows_without_a_class_default_to_scorable():
    scorable, other = split_by_scorability([{"Ticker": "AAPL"}])
    assert [r["Ticker"] for r in scorable] == ["AAPL"]
    assert other == []


# --------------------------------------------------------------------------- #
#  The page actually segments                                                 #
# --------------------------------------------------------------------------- #


def test_screener_segments_instead_of_ranking_funds_against_companies():
    assert "is_fundamentally_scorable" in SCREENER
    assert "df_equity" in SCREENER
    assert "df_other" in SCREENER

    # The funnel and the ranking chart are built from companies only.
    assert "build_shortlist(_ranked)" in SCREENER
    assert "attach_percentiles(df_equity.to_dict" in SCREENER
    # The chart draws the equity view (filtered or whole) — never the funds.
    chart = SCREENER[SCREENER.index("_chart_df = ") : SCREENER.index("st.plotly_chart")]
    assert "df_view" in chart and "df_equity" in chart
    assert "df_other" not in chart

    # The funds table exposes no score and no signal. It lives in a function
    # because two paths render it: the normal one, and the run with no companies
    # at all — where the equity ranking used to crash the page before this table
    # ever got drawn.
    other_block = SCREENER[
        SCREENER.index("def _render_non_scorable(") : SCREENER.index('if "Clase" not in df.columns:')
    ]
    assert '"Signal"' not in other_block
    assert '"Score Bar"' not in other_block
    assert '"Adj. Score"' not in other_block
    assert "no tienen estados financieros" in other_block


def test_asset_class_singleton_is_the_source_of_truth():
    assert ASSET_CLASS.scorable_classes == ("equity",)
    assert "ETF" in ASSET_CLASS.fund_quote_types
    assert "CRYPTOCURRENCY" in ASSET_CLASS.crypto_quote_types
