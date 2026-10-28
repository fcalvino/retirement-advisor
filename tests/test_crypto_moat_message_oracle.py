"""AUDIT-RESIDUALES (moat de IA) — para un cripto que no es Bitcoin, la pantalla no pide «activar un proveedor AI».

La rúbrica del moat cripto (halving, suministro fijo, hash rate) es la de Bitcoin (``BITCOIN_TICKERS``):
``CryptoAnalyzer`` no mide ningún otro activo, con IA o sin ella, y deja ``ai_reasoning = "[Moat no medido: …]"``
con ``ai_available = False``. Pero Stock Analysis decía «Moat crypto AI no disponible — activá un proveedor AI en
Settings» para ETH aun con la IA activa (activar la IA no lo arregla), y la CLI «N/A (AI disabled)» (con la IA
activa, tampoco es eso). Y para Bitcoin con la IA activa y una respuesta que falló, el mismo texto de «activá»
tampoco decía la causa. Ahora cada caso dice la suya. Sin red y sin LLM.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from analysis.crypto_analyzer import CryptoMoatDetail
from analysis.fundamental import FundamentalResult
from analysis.strategy import RetirementStrategy
from analysis.technical import TechnicalResult
from data.product_ux import crypto_moat_na_label, crypto_moat_unmeasured_text

PAGE = str(Path(__file__).resolve().parents[1] / "dashboard" / "views" / "2_Stock_Analysis.py")


# --------------------------------------------------------------------------- #
#  Los textos                                                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("ai_enabled", [True, False, None])
@pytest.mark.parametrize("symbol", ["ETH-USD", "SOL-USD", "eth-usd"])
def test_a_non_bitcoin_crypto_is_never_told_to_enable_the_ai(symbol, ai_enabled):
    text = crypto_moat_unmeasured_text(symbol, ai_enabled)
    assert "Bitcoin" in text and symbol.upper() in text.upper()
    assert "activá" not in text


def test_bitcoin_without_the_ai_is_told_to_enable_it():
    assert "activá un proveedor AI" in crypto_moat_unmeasured_text("BTC-USD", False)


def test_bitcoin_with_the_ai_on_and_no_answer_is_not_told_to_enable_it():
    text = crypto_moat_unmeasured_text("BTC-USD", True)
    assert "activá" not in text and "no devolvió" in text


@pytest.mark.parametrize("symbol,expected", [
    ("ETH-USD", "N/A (rúbrica sólo para Bitcoin)"),
    ("BTC-USD", "N/A (AI disabled)"),
    ("BTC", "N/A (AI disabled)"),
])
def test_the_cli_label(symbol, expected):
    assert crypto_moat_na_label(symbol) == expected


# --------------------------------------------------------------------------- #
#  La pantalla                                                                 #
# --------------------------------------------------------------------------- #

@pytest.fixture
def render(monkeypatch):
    import yfinance as yf

    from analysis.track_record import TrackRecordStore
    from config import MULTI_SOURCE
    from dashboard import shared

    def no_network(*args, **kwargs):
        raise AssertionError("This page test must not access yfinance")

    monkeypatch.setattr(yf, "Ticker", no_network)
    monkeypatch.setattr(MULTI_SOURCE, "enabled", False)
    monkeypatch.setattr(TrackRecordStore, "log_recommendation", lambda *a, **kw: None)
    monkeypatch.setattr(shared, "ensure_session_defaults", lambda: None)
    monkeypatch.setattr(shared, "get_price_history", lambda *a, **kw: pd.DataFrame())

    def run(symbol: str, *, ai_enabled: bool) -> AppTest:
        monkeypatch.setattr(shared, "_get_ai_config", lambda *a, **kw: SimpleNamespace(
            provider="claude", model="m", enabled=ai_enabled, api_key="k" if ai_enabled else "",
        ))
        fund = FundamentalResult(
            symbol=symbol, sector="Crypto", industry="Crypto", total_score=40, adjusted_score=40,
            current_price=3000.0, is_crypto=True,
            crypto_moat_detail=CryptoMoatDetail(ai_reasoning="[Moat no medido]"),
        )
        tech = TechnicalResult(symbol)
        decision = RetirementStrategy().decide(fund, tech)
        monkeypatch.setattr(shared, "cached_full_analysis", lambda *a: (fund, tech, decision))
        at = AppTest.from_file(PAGE, default_timeout=30)
        at.session_state["analysis_target"] = symbol
        at.session_state["universe"] = [symbol]
        at.session_state["user_prefs"] = SimpleNamespace(watched_tickers=[])
        at.session_state["portfolio"] = SimpleNamespace(positions=[])
        at.run()
        assert not at.exception, [e.message for e in at.exception]
        return at

    return run


def _captions(at: AppTest) -> str:
    return "\n".join(c.value for c in at.caption)


def test_eth_with_the_ai_on_says_the_rubric_is_bitcoins_not_to_enable_the_ai(render):
    text = _captions(render("ETH-USD", ai_enabled=True))
    assert "sólo para Bitcoin" in text
    assert "activá un proveedor AI" not in text


def test_eth_with_the_ai_off_does_not_say_to_enable_it_either(render):
    text = _captions(render("ETH-USD", ai_enabled=False))
    assert "sólo para Bitcoin" in text and "activá un proveedor AI" not in text


def test_bitcoin_with_the_ai_off_keeps_the_enable_hint(render):
    assert "activá un proveedor AI" in _captions(render("BTC-USD", ai_enabled=False))


def test_bitcoin_with_the_ai_on_and_no_answer_says_so_on_the_page(render):
    text = _captions(render("BTC-USD", ai_enabled=True))
    assert "no devolvió una evaluación" in text and "activá un proveedor AI" not in text


# --------------------------------------------------------------------------- #
#  La CLI                                                                      #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("symbol,expected", [
    ("ETH-USD", "Moat: N/A (rúbrica sólo para Bitcoin)"),
    ("BTC-USD", "Moat: N/A (AI disabled)"),
])
def test_cmd_analyze_prints_the_label_that_fits_the_asset(monkeypatch, capsys, symbol, expected):
    import main

    fund = FundamentalResult(
        symbol=symbol, sector="Crypto", industry="Crypto", total_score=40, adjusted_score=40,
        current_price=3000.0, is_crypto=True, company_name=symbol, market_cap=1e9,
    )
    tech = TechnicalResult(symbol)
    decision = RetirementStrategy().decide(fund, tech)
    monkeypatch.setattr(main, "full_analysis", lambda s: (fund, tech, decision))
    main.cmd_analyze([symbol])
    assert expected in capsys.readouterr().out
