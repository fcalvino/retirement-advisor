"""AUDIT-NUMB-1 — el crecimiento del pozo no se publica con los caminos arruinados descartados.

El motor calculaba ``median_cagr_pct`` / ``p10_cagr_pct`` como ``nanmedian`` y ``nanpercentile`` sobre los
caminos con terminal > 0. Con ruina la cifra describía a los sobrevivientes: medido con el historial
determinístico de abajo (100 000 de capital, 20 años, 2 000 simulaciones), un retiro de 4 000 arruina el 33,8 %
de los caminos, el peor 10 % termina en $0 y aun así se publicaba «−13,8 %/año»; con retiro de 5 000 (57,5 % de
ruina) la mediana termina en $0 y se publicaba «−5,8 %/año»; con 100 % de ruina, 0,0 % (el default del campo:
la rama «sin tasa» de ``pot_growth_delta`` esperaba un NaN que el motor nunca produce). La pantalla, el PDF y el
comité leían ese mismo número.

Regla: la tasa es la de la definición aplicada al **terminal publicado de todos los caminos**
(``(terminal / inicial) ** (1 / años) − 1``): la de la mediana usa ``median_terminal``, la del mal caso usa
``p10_terminal``. Un terminal ≤ 0 (la mediana o el 10 % peor se quedó sin dinero) o un capital inicial ≤ 0 no
tienen tasa: el campo es ``None`` —nunca 0—, y cada superficie dice «sin tasa». Sin red: historial inyectado.
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from data.product_ux import pot_growth_delta
from portfolio.monte_carlo import MonteCarloResult, MonteCarloSimulator

ROOT = Path(__file__).resolve().parents[1]
INITIAL = 100_000.0
YEARS = 20


def _fake_history(symbol: str, period: str = "10y", interval: str = "1wk") -> pd.DataFrame:
    n = 260
    rng = np.random.default_rng(seed=42)
    prices = 100.0 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    return pd.DataFrame({"close": prices}, index=pd.date_range("2018-01-01", periods=n, freq="W"))


def _run(withdrawal: float, *, initial: float = INITIAL, contribution: float = 0.0):
    with patch("portfolio.monte_carlo.get_history", side_effect=_fake_history):
        sim = MonteCarloSimulator(symbols=["AAPL"], seed=42)
        return sim.run(
            horizon_years=YEARS, n_sims=2000, initial_value=initial,
            annual_withdrawal=withdrawal, annual_contribution=contribution,
        )


def _growth(terminal: float, initial: float = INITIAL, years: int = YEARS) -> float:
    """The definition, written out — not the production helper."""
    return ((terminal / initial) ** (1.0 / years) - 1.0) * 100.0


# --- el motor -------------------------------------------------------------------------------------

def test_the_fields_start_as_not_measured_not_as_zero():
    assert MonteCarloResult.__dataclass_fields__["median_cagr_pct"].default is None
    assert MonteCarloResult.__dataclass_fields__["p10_cagr_pct"].default is None


def test_precondition_the_old_figure_described_the_survivors():
    """Why it matters: ruin 33,8 %, a worst decile at $0, and yet a finite worst-decile rate was published."""
    r = _run(4_000.0)
    assert 30.0 < r.prob_ruin_pct < 40.0 and r.p10_terminal == 0.0
    assert r.median_terminal > 0.0           # the median pot is alive here: its rate exists


def test_with_no_ruin_both_rates_follow_the_published_terminals():
    r = _run(0.0)
    assert r.prob_ruin_pct == 0.0
    assert r.median_cagr_pct == pytest.approx(_growth(r.median_terminal), rel=1e-9)
    assert r.p10_cagr_pct == pytest.approx(_growth(r.p10_terminal), rel=1e-9)


def test_with_some_ruin_the_median_is_the_rate_of_the_median_pot_not_of_the_survivors():
    r = _run(4_000.0)                                        # ruin 33,8 %: median pot $12 750 > 0, p10 pot $0
    assert r.median_cagr_pct == pytest.approx(_growth(r.median_terminal), rel=1e-9)
    assert r.median_cagr_pct < -9.0                          # the survivors' median said −5,55 %
    assert r.p10_cagr_pct is None                            # the worst decile ended with no money: no rate


@pytest.mark.parametrize("withdrawal", [5_000.0, 6_000.0, 30_000.0])
def test_when_the_median_pot_ends_with_no_money_neither_rate_exists(withdrawal):
    r = _run(withdrawal)
    assert r.prob_ruin_pct > 50.0 and r.median_terminal == 0.0
    assert r.median_cagr_pct is None                         # old: −5,8 % (survivors) or 0,0 % (all ruined)
    assert r.p10_cagr_pct is None


def test_a_plan_with_no_starting_capital_has_no_rate():
    """Pot growth divides by the initial capital: with none it is undefined — and not 0.0."""
    r = _run(0.0, initial=0.0, contribution=12_000.0)
    assert r.median_terminal > 0.0
    assert r.median_cagr_pct is None and r.p10_cagr_pct is None


def test_a_rate_is_never_a_nan_or_an_infinity():
    for w in (0.0, 4_000.0, 30_000.0):
        r = _run(w)
        for v in (r.median_cagr_pct, r.p10_cagr_pct):
            assert v is None or math.isfinite(v)


# --- la pantalla: el texto ---------------------------------------------------------------------------

@pytest.mark.parametrize("flows", [True, False])
@pytest.mark.parametrize("case", ["median", "p10"])
def test_a_missing_rate_says_there_is_none_and_prints_no_number(flows, case):
    text = pot_growth_delta(None, flows, case=case)
    assert "sin tasa" in text
    assert "%" not in text and "nan" not in text.lower() and "0.0" not in text


def test_the_text_names_whose_pot_ended_with_no_money():
    assert "mediana" in pot_growth_delta(None, True, case="median")
    assert "p10" in pot_growth_delta(None, True, case="p10")
    assert "capital inicial" in pot_growth_delta(None, True, has_capital=False)
    # It is the chip under an st.metric, which cuts at ~25 characters: «sin tasa» must come first.
    for case in ("median", "p10"):
        assert pot_growth_delta(None, True, case=case).startswith("sin tasa") and len(pot_growth_delta(None, True, case=case)) <= 26


def test_a_real_rate_still_prints_as_before():
    assert pot_growth_delta(-5.6, True) == "-5.6%/año de crecimiento del pozo"
    assert pot_growth_delta(6.3, False) == "6.3%/año (CAGR)"


def test_the_help_no_longer_says_the_figure_describes_the_survivors():
    from data.product_ux import pot_growth_help

    text = pot_growth_help(True).lower()
    assert "sobrevivieron" not in text
    assert "sin dinero" in text and "sin tasa" in text


# --- el PDF -------------------------------------------------------------------------------------------

def test_the_pdf_risk_table_prints_a_dash_for_a_missing_rate_not_0_0_percent():
    from reports.investment_plan import InvestmentPlanReport, _styles

    mc = _mc(median_cagr_pct=None, p10_cagr_pct=None, prob_ruin_pct=100.0)
    table = _risk_table(InvestmentPlanReport(), _styles(), mc)
    cells = {row[0]: row[1] for row in table._cellvalues[1:]}
    mediano = next(v for k, v in cells.items() if "mediano" in k)
    mala = next(v for k, v in cells.items() if "mala racha" in k)
    assert mediano == "N/D" and mala == "N/D"


def test_the_pdf_risk_table_still_prints_a_measured_rate():
    from reports.investment_plan import InvestmentPlanReport, _styles

    mc = _mc(median_cagr_pct=-5.6, p10_cagr_pct=-9.0, prob_ruin_pct=1.0)
    cells = {row[0]: row[1] for row in _risk_table(InvestmentPlanReport(), _styles(), mc)._cellvalues[1:]}
    assert next(v for k, v in cells.items() if "mediano" in k) == "-5.6%"
    assert next(v for k, v in cells.items() if "mala racha" in k) == "-9.0%"


def _mc(**kw) -> MonteCarloResult:
    base = dict(n_sims=2000, horizon_years=YEARS, initial_value=INITIAL, annual_withdrawal=0.0, target_value=0.0)
    base.update(kw)
    return MonteCarloResult(**base)


def _risk_table(report, styles, mc):
    from reportlab.platypus import Table

    from reports.investment_plan import ReportOptions

    options = ReportOptions(include_charts=False)
    flowables = report._section_risk(styles, mc, {"horizon_years": 20, "initial_value": 100_000.0}, options)
    return next(f for f in flowables if isinstance(f, Table))


# --- el plan guardado y el comité ---------------------------------------------------------------------

def test_a_saved_plan_keeps_a_missing_rate_as_none_and_does_not_crash():
    from types import SimpleNamespace

    from data.plan_store import PlanSnapshot

    mc = _mc(median_cagr_pct=None, p10_cagr_pct=None, prob_ruin_pct=100.0)
    snap = PlanSnapshot.from_session(
        name="x", opt_result=SimpleNamespace(profile_name="Moderado", tickers=[], metrics={}),
        mc_result=mc, mc_params={"horizon_years": 20},
    )
    assert snap.mc_summary["median_cagr_pct"] is None


def test_the_committee_prompt_says_the_rate_is_not_available_and_does_not_invent_zero():
    from analysis.committee_prompts import portfolio_committee_context_block

    ctx = {
        "expected_return_pct": 5.0, "prob_target_pct": 10.0, "p10_terminal": 0.0,
        "median_cagr_pct": None, "mc_has_cash_flows": True, "sector_weights": {}, "position_weights": {},
    }
    text = portfolio_committee_context_block(ctx)
    assert "mediano: n/d" in text or "mediano: —" in text
    assert "0.0%" not in text.split("mediano")[-1][:40]


# --- la versión del motor --------------------------------------------------------------------------------

def test_the_engine_version_moved_so_saved_plans_are_marked_stale():
    from config import ENGINE_VERSION
    from data.product_ux import ENGINE_CHANGELOG, engine_staleness_reasons

    assert ENGINE_VERSION >= "2026.10-tier24"
    assert ENGINE_CHANGELOG[-1][0] == ENGINE_VERSION
    reasons = engine_staleness_reasons("2026.10-tier23")
    assert len(reasons) == 1 and "sin dinero" in reasons[0]


# --- la página de Simulaciones ------------------------------------------------------------------------

def test_the_simulations_page_says_no_rate_instead_of_zero_percent_under_the_median_and_the_bad_run():
    from streamlit.testing.v1 import AppTest

    from tests.test_eo4c2_ui_oracle import SIM_PAGE, _fake_mc

    mc = _fake_mc()
    mc.median_terminal, mc.p10_terminal = 0.0, 0.0
    mc.median_cagr_pct, mc.p10_cagr_pct = None, None
    at = AppTest.from_file(str(SIM_PAGE), default_timeout=120)
    at.session_state["mc_result"] = mc
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    deltas = {m.label: m.delta for m in at.metric}
    assert "sin tasa" in deltas["Valor más probable (mediana)"]
    assert "sin tasa" in deltas["Mala racha (p10)"]
    assert all("0.0%" not in str(d) for d in deltas.values())
