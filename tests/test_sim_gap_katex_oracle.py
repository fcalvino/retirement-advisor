"""Oráculo SIM-GAP-PCT + KATEX-DOLLAR-PLAN: lo que el usuario lee en esos bloques.

**SIM-GAP-PCT.** «Dos escenarios» (Simulaciones) decía que la mediana conservadora
es «~X% más baja que el realista» con ``X = realista / conservadora − 1``, que es
cuánto más **alta** es la realista: con 3.155.332 y 1.220.635 escribía «~158%» y la
conservadora es un 61 % más baja. Una baja no pasa del 100 %. El porcentaje de
referencia sale de la definición (``1 − conservadora / realista``), calculado acá
con los números de la QA en vivo de REALISTIC-TAIL-CLIP.

**KATEX-DOLLAR-PLAN.** Streamlit lee un par de ``$`` en markdown como KaTeX
(CONTEXT §8): «Aportar ~$2,000/mes … $24,000» se ve «\\*\\*Aportar ~» y el resto en
monoespaciado. Cada sitio de abajo dibujaba montos con ``$`` crudo; el oráculo es
el texto que llega al elemento de Streamlit, sin un ``$`` sin escapar.

Sin red: el Monte Carlo y el análisis están stubbeados; el store de planes es el
temporal de ``test_plan_page_runtime``.
"""

from __future__ import annotations

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_plan_page_runtime import stores  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
SIM_PAGE = ROOT / "dashboard" / "views" / "7_Simulaciones.py"

CONSERVATIVE_MEDIAN = 1_220_635.0

_RAW_DOLLAR = re.compile(r"(?<!\\)\$")


def _fake_mc(*, median_terminal: float):
    """Un Monte Carlo terminado: la página lo lee de la sesión sin correr nada."""
    from portfolio.monte_carlo import MonteCarloResult

    horizon = 20
    mc = MonteCarloResult(
        n_sims=100, horizon_years=horizon, initial_value=100_000.0,
        annual_withdrawal=0.0, target_value=0.0,
    )
    mc.median_terminal = median_terminal
    mc.p10_terminal = median_terminal * 0.4
    mc.p25_terminal = median_terminal * 0.7
    mc.p75_terminal = median_terminal * 1.3
    mc.p90_terminal = median_terminal * 1.7
    mc.median_cagr_pct = 6.7
    mc.years = list(range(horizon + 1))
    mc.fan_paths = {
        y: {p: 100_000.0 * ((1 + p / 1000) ** y) for p in (5, 10, 25, 50, 75, 90, 95)}
        for y in range(horizon + 1)
    }
    return mc


def _two_scenarios_block() -> str:
    """EO-4c-2: «Dos referencias» se fue; el bloque que dibuja montos ahí es «Tres
    Escenarios». La prueba de KaTeX sigue sobre ese bloque. SIM-GAP-PCT (el
    porcentaje entre la Estimación y la historia reciente) se fue con su bloque."""
    at = AppTest.from_file(str(SIM_PAGE), default_timeout=120)
    mc = _fake_mc(median_terminal=CONSERVATIVE_MEDIAN)
    mc.scenario = "central"
    mc.scenarios = {
        n: {"median_terminal": CONSERVATIVE_MEDIAN * k, "p10_terminal": CONSERVATIVE_MEDIAN * k * 0.4,
            "p90_terminal": CONSERVATIVE_MEDIAN * k * 1.7, "prob_achieve_target_pct": 0.0,
            "n_sims": 100}
        for n, k in (("pesimista", 0.8), ("central", 1.0), ("optimista", 1.3))
    }
    at.session_state["mc_result"] = mc
    at.run()
    assert not at.exception, [str(e)[:400] for e in at.exception]
    blocks = [i.value for i in at.info if "Tres Escenarios" in (i.value or "")]
    assert len(blocks) == 1, "el bloque «Tres Escenarios» no se dibujó"
    return blocks[0]


# --------------------------------------------------------------------------- #
#  KATEX-DOLLAR-PLAN                                                           #
# --------------------------------------------------------------------------- #

def _assert_no_raw_dollar(text: str) -> None:
    assert "$" in text, "el sitio no dibujó montos: el test no prueba nada"
    assert not _RAW_DOLLAR.search(text), f"`$` sin escapar (KaTeX): {text!r}"


def test_the_two_scenarios_block_escapes_its_amounts():
    _assert_no_raw_dollar(_two_scenarios_block())


def test_the_drags_median_block_escapes_its_amounts(monkeypatch):
    """Sólo se dibuja al correr la simulación, con drags activos."""
    from dashboard import shared

    mc = _fake_mc(median_terminal=CONSERVATIVE_MEDIAN)
    mc.total_annual_drag_pct = 0.25
    mc.base_median_terminal = CONSERVATIVE_MEDIAN * 1.05
    monkeypatch.setattr(shared, "cached_monte_carlo", lambda *a, **k: mc)

    at = AppTest.from_file(str(SIM_PAGE), default_timeout=120)
    at.run()
    [run] = [b for b in at.button if b.label == "▶ Ejecutar simulación Monte Carlo"]
    run.click().run()
    assert not at.exception, [str(e)[:400] for e in at.exception]
    blocks = [i.value for i in at.info if "con drags" in (i.value or "")]
    assert len(blocks) == 1, "el bloque de la mediana con drags no se dibujó"
    _assert_no_raw_dollar(blocks[0])


def test_the_active_plan_checklist_escapes_its_amounts(stores):  # noqa: F811
    """«Aportar ~$2,000/mes» y «Meta de aporte anual: $24,000» en un mismo ítem."""
    from tests.test_pdf_zero_savings_oracle import _checklist, _Prefs
    from tests.test_plan_page_runtime import _snap

    text = _checklist(stores, _Prefs(), {**_snap().mc_summary, "monthly_savings": 2_000.0})
    assert "2,000/mes" in text
    _assert_no_raw_dollar(text)


def test_the_suggested_shares_caption_escapes_its_amounts(monkeypatch, tmp_path):
    """Hallado en el barrido del 2026-10-03, fuera de la fila: «costo base $X →
    … acciones @ $Y» en un ``st.caption``, que también corre markdown."""
    from dataclasses import replace

    import pandas as pd

    import portfolio.tracker as tracker_mod
    from analysis import track_record
    from analysis.eval_cases import golden_cases
    from analysis.strategy import RetirementStrategy
    from analysis.track_record import TrackRecordStore
    from dashboard import shared
    from portfolio.tracker import Portfolio

    case = golden_cases()[0]
    fund = replace(case.fund, symbol="AAPL", currency="USD", current_price=200.0)
    decision = RetirementStrategy().decide(fund, case.tech)
    decision.recommended_max_allocation_pct = 5.0
    monkeypatch.setattr(shared, "cached_full_analysis", lambda *a, **k: (fund, case.tech, decision))
    monkeypatch.setattr(track_record, "track_record_store", TrackRecordStore(db_path=str(tmp_path / "tr.db")))
    monkeypatch.setattr(tracker_mod, "get_info", lambda s: {"currentPrice": 100.0, "currency": "USD"})
    monkeypatch.setattr(shared, "get_price_history", lambda *a, **k: pd.DataFrame())
    book = Portfolio(file_path=tmp_path / "portfolio.json")
    assert book.add_position("MSFT", 100, 100.0, "2026-01-02") is None

    at = AppTest.from_file(str(ROOT / "dashboard" / "views" / "2_Stock_Analysis.py"), default_timeout=60)
    at.session_state["analysis_target"] = "AAPL"
    at.session_state["portfolio"] = book
    at.run()
    assert not at.exception, [str(e)[:400] for e in at.exception]
    captions = [c.value for c in at.caption if "Sugerido por la IA" in (c.value or "")]
    assert len(captions) == 1, "el caption de acciones sugeridas no se dibujó"
    _assert_no_raw_dollar(captions[0])


def test_the_gap_levers_escape_their_amounts():
    """EO-4a, QA en vivo: con la probabilidad bajo 70 % las palancas dicen «Sumá
    ~$307/mes ($3,681/año)», y ese par de `$` se veía como fórmula."""
    at = AppTest.from_file(str(SIM_PAGE), default_timeout=120)
    mc = _fake_mc(median_terminal=356_192.0)
    mc.target_value = 500_000.0
    mc.prob_achieve_target_pct = 38.2
    at.session_state["mc_result"] = mc
    at.run()
    assert not at.exception, [str(e)[:400] for e in at.exception]
    levers = [m.value for m in at.markdown if "Aportar más por mes" in (m.value or "")]
    assert len(levers) == 1, "la palanca de aporte no se dibujó"
    _assert_no_raw_dollar(levers[0])
