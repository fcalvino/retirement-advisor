"""Global Screener universe — integrity, filters, non-US classification, and
that the screens sharing the universe files do not change by accident.

No network: the universe is a versioned file, and the row builder is fed
stand-in analysis objects instead of yfinance.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.asset_class import CRYPTO, EQUITY, FUND, classify_asset, is_fundamentally_scorable
from analysis.ranking import FilterCriteria, apply_filters, preset_gap
from config import UNIVERSE
from data import universe_loader
from data.universe_loader import (
    TickerMeta,
    apply_universe_metadata,
    get_effective_universe,
    list_universes,
    load_universe,
    load_universe_metadata,
    optimizer_universes,
)

_KEY = "global_quality"
_UNIVERSES = Path(universe_loader.__file__).parent / "universes"
_RAW = json.loads((_UNIVERSES / f"{_KEY}.json").read_text(encoding="utf-8"))

#: The five universes that existed before the global one, frozen as they were.
#: Screener, Optimizer, Backtesting and Alertas all read these; growing the
#: Screener must not move a single symbol in them.
_LEGACY_COUNTS = {
    "default": 39, "growth_moat": 27, "dividend_focus": 66,
    "us_quality": 85, "latam_adrs": 27,
}


# --------------------------------------------------------------------------- #
#  Universe integrity                                                         #
# --------------------------------------------------------------------------- #


def _suffix(symbol: str) -> str:
    return symbol[symbol.rfind("."):] if "." in symbol else ""


def test_every_entry_is_a_dict_with_ticker_country_and_industry():
    for entry in _RAW["tickers"]:
        assert isinstance(entry, dict), entry
        assert entry.get("ticker"), entry
        assert entry.get("country") in UNIVERSE.countries, entry
        assert entry.get("industry") in UNIVERSE.industries, entry


def test_no_duplicate_tickers():
    symbols = [e["ticker"].upper() for e in _RAW["tickers"]]
    dupes = sorted({s for s in symbols if symbols.count(s) > 1})
    assert not dupes, dupes


def test_suffixes_are_known_exchanges_and_the_loader_keeps_every_ticker():
    for entry in _RAW["tickers"]:
        assert _suffix(entry["ticker"]) in UNIVERSE.exchange_suffixes, entry["ticker"]
    # A silent drop was the old failure: len > 7 discarded WALMEX.MX / NOVO-B.CO.
    assert len(load_universe(_KEY)) == len(_RAW["tickers"])
    assert {"WALMEX.MX", "NOVO-B.CO", "GFNORTEO.MX"} <= set(load_universe(_KEY))


def test_symbols_are_well_formed():
    pattern = re.compile(r"^[A-Z0-9][A-Z0-9\-]*(\.[A-Z]{1,2})?$")
    for entry in _RAW["tickers"]:
        assert pattern.match(entry["ticker"]), entry["ticker"]


def test_merval_is_excluded_on_purpose():
    # ARS with inflation: ROE / P/E are not comparable (see UniverseConfig).
    assert ".BA" not in UNIVERSE.exchange_suffixes
    assert not any(e["ticker"].endswith(".BA") for e in _RAW["tickers"])


def test_breadth_countries_regions_and_industries():
    countries = {e["country"] for e in _RAW["tickers"]}
    industries = {e["industry"] for e in _RAW["tickers"]}
    assert len(_RAW["tickers"]) >= 100
    assert industries == set(UNIVERSE.industries)  # all 11 sectors covered
    for region in (
        {"United Kingdom", "Germany", "France", "Switzerland"},  # Europe
        {"Japan", "Australia"},                                  # APAC
        {"Canada", "Brazil", "Mexico"},                          # Americas ex-US
    ):
        assert region <= countries, region - countries


def test_the_default_first_run_already_spans_countries_and_sectors():
    # With no previous run, the Screener analyses a file-order prefix of
    # SCREENER.default_max_tickers. Grouped by country, that prefix was 25 US
    # names; the file is interleaved so any prefix is diverse.
    from config import SCREENER

    head = _RAW["tickers"][: SCREENER.default_max_tickers]
    assert len({e["country"] for e in head}) >= 10
    assert len({e["industry"] for e in head}) >= 8


def test_metadata_matches_the_symbol_list():
    meta = load_universe_metadata(_KEY)
    assert set(meta) == set(load_universe(_KEY))
    assert meta["7203.T"] == TickerMeta("Japan", "Consumer Cyclical")


def test_description_count_matches_the_file():
    assert str(len(_RAW["tickers"])) in _RAW["description"]


# --------------------------------------------------------------------------- #
#  Legacy universes and their consumers do not move                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key,count", sorted(_LEGACY_COUNTS.items()))
def test_legacy_universes_are_unchanged(key, count):
    assert len(load_universe(key)) == count
    # Symbol-only files carry no curated metadata: the feed keeps deciding.
    assert load_universe_metadata(key) == {}


def test_legacy_display_order_is_preserved_and_global_is_appended():
    keys = list_universes()
    assert keys[: len(_LEGACY_COUNTS)] == [
        "default", "growth_moat", "dividend_focus", "us_quality", "latam_adrs",
    ]
    assert _KEY in keys


def test_optimizer_lists_do_not_grow_with_the_screener_universe():
    # "Combinar universos" and "Comparar todos" read this list; they work on
    # raw price series with no FX conversion.
    assert _KEY in UNIVERSE.screener_only
    assert optimizer_universes() == [k for k in list_universes() if k != _KEY]
    assert set(optimizer_universes()) == set(_LEGACY_COUNTS)


def test_customs_on_a_dict_universe_still_dedupe():
    base = load_universe(_KEY)
    tickers, customs = get_effective_universe(_KEY, ["sap.de", "ZZZZ"])
    assert customs == ["ZZZZ"]
    assert tickers == base + ["ZZZZ"]


def test_longer_limit_still_rejects_garbage():
    assert not universe_loader._is_valid_ticker("X" * (UNIVERSE.max_ticker_len + 1))
    assert not universe_loader._is_valid_ticker("BAD TICKER")
    assert not universe_loader._is_valid_ticker({"ticker": "AAPL"})


# --------------------------------------------------------------------------- #
#  Country / industry overlay and filters                                     #
# --------------------------------------------------------------------------- #


def _row(ticker, sector="Technology", pais="", **extra):
    return {"Ticker": ticker, "Company": ticker, "Sector": sector, "País": pais,
            "Signal": "🟩 BUY", "Adj. Score": 70.0, **extra}


def test_curated_country_wins_and_feed_fills_the_rest():
    meta = {"SAP.DE": TickerMeta("Germany", "Technology")}
    rows = [_row("SAP.DE", pais="Deutschland"), _row("TSLA", pais="United States"), _row("ZZZZ")]
    out = apply_universe_metadata(rows, meta)
    assert [r["País"] for r in out] == ["Germany", "United States", UNIVERSE.unknown_country]
    assert rows[0]["País"] == "Deutschland"  # inputs are not mutated


def test_rows_stored_before_this_change_get_a_country_cell():
    old = {"Ticker": "AAPL", "Sector": "Technology"}  # no "País" key at all
    assert apply_universe_metadata([old], {})[0]["País"] == UNIVERSE.unknown_country


def test_curated_industry_only_repairs_a_missing_sector():
    meta = {"X.T": TickerMeta("Japan", "Industrials"), "Y.T": TickerMeta("Japan", "Industrials")}
    out = apply_universe_metadata([_row("X.T", sector="Unknown"), _row("Y.T", sector="Technology")], meta)
    assert out[0]["Sector"] == "Industrials"
    assert out[1]["Sector"] == "Technology"  # the feed stays authoritative


def test_country_filter_narrows_and_combines_with_sector():
    rows = [
        _row("SAP.DE", "Technology", "Germany"),
        _row("SIE.DE", "Industrials", "Germany"),
        _row("7203.T", "Consumer Cyclical", "Japan"),
        _row("AAPL", "Technology", "United States"),
    ]
    by_country = apply_filters(rows, FilterCriteria(countries=("Germany", "Japan")))
    assert [r["Ticker"] for r in by_country] == ["SAP.DE", "SIE.DE", "7203.T"]
    both = apply_filters(rows, FilterCriteria(countries=("Germany",), sectors=("Technology",)))
    assert [r["Ticker"] for r in both] == ["SAP.DE"]
    assert FilterCriteria(countries=("Japan",)).is_active()
    assert apply_filters(rows, FilterCriteria()) == rows  # no filter = no change


def test_country_filter_with_no_match_is_empty_not_an_error():
    assert apply_filters([_row("AAPL", pais="United States")], FilterCriteria(countries=("Japan",))) == []


def test_preset_gap_reports_a_country_the_run_lacks():
    gap = preset_gap(FilterCriteria(countries=("Japan",)), FilterCriteria(countries=("Germany",)))
    assert gap == {"País": ("Japan",)}


# --------------------------------------------------------------------------- #
#  Non-US asset classification                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("sym", ["SAP.DE", "7203.T", "NESN.SW", "VALE3.SA", "NOVO-B.CO", "0700.HK"])
def test_local_listings_with_equity_quote_type_are_scorable(sym):
    cls = classify_asset(sym, quote_type="EQUITY", sector="Industrials")
    assert cls == EQUITY and is_fundamentally_scorable(cls)


@pytest.mark.parametrize("sym", ["SAP.DE", "7203.T", "SHEL.L"])
def test_local_listings_without_quote_type_default_to_equity(sym):
    assert classify_asset(sym, quote_type=None, sector="") == EQUITY


@pytest.mark.parametrize("sym", ["CSPX.L", "IWDA.AS", "1306.T"])
def test_foreign_etfs_are_funds_by_quote_type(sym):
    cls = classify_asset(sym, quote_type="ETF")
    assert cls == FUND and not is_fundamentally_scorable(cls)


def test_foreign_crypto_quote_is_crypto():
    assert classify_asset("BTC-EUR", quote_type="CRYPTOCURRENCY") == CRYPTO


# --------------------------------------------------------------------------- #
#  Tickers without data / with a different currency                           #
# --------------------------------------------------------------------------- #


def _fund(**kw):
    base = dict(
        company_name="Toyota Motor Corp", sector="Consumer Cyclical", country="Japan",
        currency="JPY", asset_class="equity", adjusted_score=70.0, raw_adjusted_score=70.0,
        total_score=65.0, consistency_score=10.0, piotroski_score=7, moat_score=12.0,
        moat_classification="Narrow", tailwind_classification="Neutral", tailwind_score=0.0,
        pe_ratio=8.6, roe=12.4, revenue_cagr_5y=5.0, revenue_cagr_years=3,
        dividend_yield=3.3, margin_of_safety_pct=10.0, current_price=3000.0,
        data_quality={"level": "good"},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _row_for(sym, fund, monkeypatch):
    from dashboard import shared

    monkeypatch.setattr(shared, "decision_explanation", lambda d: {
        "headline": "h", "confidence": "MEDIUM", "ai_confidence": None,
        "why": [], "risks": [], "full_headline": "h",
    })
    monkeypatch.setattr(shared, "_track_payload", lambda f, d: {})
    decision = SimpleNamespace(action="BUY", action_emoji="🟩")
    tech = SimpleNamespace(signal="NEUTRAL")
    return shared._format_row_for_display(shared._extract_row_data(sym, fund, tech, decision))


def test_row_carries_quote_currency_and_country(monkeypatch):
    row = _row_for("7203.T", _fund(), monkeypatch)
    assert row["Moneda"] == "JPY"
    assert row["País"] == "Japan"
    assert row["Price"] == 3000.0  # not converted: the unit is in "Moneda"


def test_pence_quote_is_labelled_not_rescaled(monkeypatch):
    row = _row_for("SHEL.L", _fund(currency="GBp", country="United Kingdom", current_price=2650.0), monkeypatch)
    assert (row["Moneda"], row["Price"]) == ("GBp", 2650.0)


def test_empty_feed_still_builds_a_row(monkeypatch):
    # A symbol whose info came back empty: no country, no currency, no sector.
    row = _row_for("RO.SW", _fund(country="", currency="", sector="Unknown"), monkeypatch)
    assert row["Moneda"] == ""
    fixed = apply_universe_metadata([row], {"RO.SW": TickerMeta("Switzerland", "Healthcare")})[0]
    assert (fixed["País"], fixed["Sector"]) == ("Switzerland", "Healthcare")


def test_results_cached_before_the_field_existed_do_not_break(monkeypatch):
    fund = _fund()
    del fund.currency, fund.country
    row = _row_for("AAPL", fund, monkeypatch)
    assert (row["Moneda"], row["País"]) == ("", "")


def test_engine_records_quote_currency_from_the_feed():
    from analysis.fundamental import FundamentalAnalyzer, FundamentalResult

    result = FundamentalResult(symbol="SHEL.L")
    info = {"longName": "Shell plc", "country": "United Kingdom", "sector": "Energy",
            "currency": "GBp", "financialCurrency": "USD", "quoteType": "EQUITY",
            "currentPrice": 2650.0}
    FundamentalAnalyzer._populate_identity(FundamentalAnalyzer.__new__(FundamentalAnalyzer), result, "SHEL.L", info)
    assert (result.currency, result.financial_currency, result.country) == ("GBp", "USD", "United Kingdom")
    assert result.asset_class == EQUITY
