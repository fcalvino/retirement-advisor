"""Oracle tests for converting a far-away USD projection into pesos.

Backlog row U2-5 (oleada 2 · P0 · negocio · fuente P2)
-----------------------------------------------------
  hallazgo : Mediana 20-30y a ARS al FX spot.
  evidencia: Simulaciones / Plan; defaults 1000/1200; except pass.
  fix      : No convertir terminales lejanos al spot o inflar FX; no placeholders
             como dato.
  oráculo  : UI no muestra USD30 x spot.

Why this file exists
--------------------
``MonteCarloResult.median_terminal`` is USD **nominal at the horizon**: the paths
bootstrap nominal weekly returns and the drag layer models fees, taxes and
rebalancing — never inflation. Both surfaces multiplied it by *today's* rate::

    ar_dual_amounts(float(mc.median_terminal),          # USD in year 30
                    usd_ars_oficial=float(AR_FX.usd_ars_oficial))   # AR$ today

so the biggest number on the screen had its two halves thirty years apart. The
same page computes ``median_terminal / (1 + i) ** n`` seventy lines earlier and
the ARS block ignored it.

Three separate defects travelled together and each gets its own oracle here:

1. mixed units — a nominal terminal converted at spot (this is the headline);
2. invented rates — ``ArFxConfig`` defaults 1000/1200 with ``USD_ARS_*`` unset
   anywhere in the repo, whose 20 % "brecha" was rendered as a market fact;
3. ``except Exception: pass`` around both blocks, imports included, so any of
   the above could fail without a trace.

The reference implementations below are written from the definition (deflate,
then convert), never from the production source: comparing the engine against
its previous self freezes the bug instead of finding it (CONTEXT.md §5).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from data.product_ux import (
    AR_BASIS_PRESENT_VALUE,
    AR_BASIS_TODAY,
    ar_dual_amounts,
    ar_dual_context,
    format_ar_dual_line,
    present_value_usd,
)

ROOT = Path(__file__).resolve().parents[1]
SIM_PAGE = ROOT / "dashboard" / "pages" / "7_Simulaciones.py"
PLAN_PAGE = ROOT / "dashboard" / "pages" / "12_Plan.py"


# --------------------------------------------------------------------------- #
#  Reference implementation — from the definition, not from the code           #
# --------------------------------------------------------------------------- #

def reference_pesos(
    nominal_usd: float,
    *,
    years: float,
    annual_inflation_pct: float,
    rate: float,
) -> float:
    """Pesos of TODAY for a nominal USD amount ``years`` away.

    Deflate by compounding inflation backwards one year at a time (a slow loop,
    on purpose), then apply today's rate. Today's rate is only ever applied to
    today's dollars — that is the whole content of the fix.
    """
    usd = float(nominal_usd)
    i = float(annual_inflation_pct) / 100.0
    whole, frac = divmod(float(years), 1.0)
    for _ in range(int(whole)):
        usd /= 1.0 + i
    if frac:
        usd /= (1.0 + i) ** frac
    return usd * float(rate)


class _FakeFx:
    """Stand-in for ``config.AR_FX`` with no import-time env coupling."""

    def __init__(self, *, oficial=1000.0, parallel=1200.0, source="placeholder", enabled=True):
        self.enabled = enabled
        self.usd_ars_oficial = oficial
        self.usd_ars_parallel = parallel
        self.rate_source = source
        self.rate_asof = ""


# --------------------------------------------------------------------------- #
#  A — the headline oracle: the UI must not show USD-at-year-30 × spot         #
# --------------------------------------------------------------------------- #

def test_a_a_thirty_year_median_is_never_multiplied_by_todays_rate():
    """The literal U2-5 oracle."""
    median_terminal, spot, inflation, horizon = 700_000.0, 1_000.0, 3.0, 30

    dual = ar_dual_amounts(
        median_terminal,
        usd_ars_oficial=spot,
        horizon_years=horizon,
        usd_inflation_pct=inflation,
    )

    naive = median_terminal * spot                 # what the page used to print
    assert dual["ars_oficial"] != pytest.approx(naive)
    # ...and it is short by exactly the deflator, not by some other amount.
    # (`abs=1`: the peso figure is rounded to the whole peso for display.)
    assert dual["ars_oficial"] / naive == pytest.approx((1 + inflation / 100) ** -horizon, rel=1e-6)
    assert dual["ars_oficial"] == pytest.approx(
        reference_pesos(median_terminal, years=horizon, annual_inflation_pct=inflation, rate=spot),
        abs=1.0,
    )
    # The nominal figure is kept, so the UI can still show where it came from.
    assert dual["usd_nominal"] == pytest.approx(median_terminal)
    assert dual["basis"] == AR_BASIS_PRESENT_VALUE


@pytest.mark.parametrize("horizon", [1, 5, 20, 30, 40])
@pytest.mark.parametrize("inflation", [0.5, 2.0, 3.0, 5.0])
@pytest.mark.parametrize("rate", [850.0, 1000.0, 1_450.5])
def test_a_b_engine_agrees_with_the_reference_across_the_grid(horizon, inflation, rate):
    dual = ar_dual_amounts(
        1_234_567.0,
        usd_ars_oficial=rate,
        usd_ars_parallel=rate * 1.35,
        horizon_years=horizon,
        usd_inflation_pct=inflation,
    )
    assert dual["ars_oficial"] == pytest.approx(
        reference_pesos(1_234_567.0, years=horizon, annual_inflation_pct=inflation, rate=rate),
        abs=1.0,
    )
    assert dual["ars_parallel"] == pytest.approx(
        reference_pesos(1_234_567.0, years=horizon, annual_inflation_pct=inflation, rate=rate * 1.35),
        abs=1.0,
    )


def test_a_c_the_further_away_the_smaller_the_peso_figure():
    """Monotonicity: purchasing power cannot grow by sitting further out."""
    pesos = [
        ar_dual_amounts(
            500_000.0, usd_ars_oficial=1000.0, horizon_years=h, usd_inflation_pct=3.0
        )["ars_oficial"]
        for h in (0, 5, 10, 20, 30)
    ]
    assert pesos == sorted(pesos, reverse=True)


def test_a_d_present_value_usd_matches_the_definition():
    assert present_value_usd(1000.0, annual_inflation_pct=3.0, years=0) == pytest.approx(1000.0)
    assert present_value_usd(1000.0, annual_inflation_pct=0.0, years=30) == pytest.approx(1000.0)
    assert present_value_usd(1000.0, annual_inflation_pct=3.0, years=1) == pytest.approx(1000 / 1.03)
    assert present_value_usd(1000.0, annual_inflation_pct=3.0, years=30) == pytest.approx(
        1000 / 1.03 ** 30
    )


# --------------------------------------------------------------------------- #
#  B — the mistake cannot be made silently                                     #
# --------------------------------------------------------------------------- #

def test_b_a_a_far_away_amount_without_an_inflation_assumption_raises():
    with pytest.raises(ValueError) as exc:
        ar_dual_amounts(700_000.0, usd_ars_oficial=1000.0, horizon_years=30)
    assert "U2-5" in str(exc.value)


def test_b_b_zero_horizon_still_converts_at_spot():
    """A target the user typed is already in today's dollars — spot is exact."""
    dual = ar_dual_amounts(500_000.0, usd_ars_oficial=1000.0, label="meta")
    assert dual["basis"] == AR_BASIS_TODAY
    assert dual["ars_oficial"] == pytest.approx(500_000_000.0)
    assert dual["usd"] == pytest.approx(dual["usd_nominal"])


def test_b_c_the_pre_existing_contract_is_unchanged_for_todays_dollars():
    """Backwards compatibility with tests/test_product_ux.py::test_ar_dual_amounts_and_brecha."""
    dual = ar_dual_amounts(10_000, usd_ars_oficial=1000, usd_ars_parallel=1200, label="capital")
    assert dual["usd"] == 10_000
    assert dual["ars_oficial"] == 10_000_000
    assert dual["ars_parallel"] == 12_000_000
    assert dual["brecha_pct"] == pytest.approx(20.0)


def test_b_d_a_bad_rate_is_still_rejected():
    with pytest.raises(ValueError):
        ar_dual_amounts(100, usd_ars_oficial=0)


# --------------------------------------------------------------------------- #
#  C — placeholder rates are not market data                                   #
# --------------------------------------------------------------------------- #

def test_c_a_placeholder_rates_do_not_produce_a_brecha():
    dual = ar_dual_amounts(
        10_000, usd_ars_oficial=1000, usd_ars_parallel=1200, rate_source="placeholder"
    )
    assert dual["brecha_pct"] is None
    assert "cotización" in dual["brecha_omitted_reason"]


def test_c_b_real_rates_do_produce_one():
    dual = ar_dual_amounts(
        10_000, usd_ars_oficial=1000, usd_ars_parallel=1200, rate_source="env"
    )
    assert dual["brecha_pct"] == pytest.approx(20.0)


def test_c_c_config_knows_where_its_rates_came_from(monkeypatch):
    """No `importlib.reload(config)` here: it rebinds every singleton in the
    module while the rest of the codebase keeps the old objects."""
    import config as cfg

    monkeypatch.delenv("USD_ARS_OFICIAL", raising=False)
    monkeypatch.delenv("USD_ARS_PARALLEL", raising=False)
    default = cfg.ArFxConfig()
    assert default.rate_source == "placeholder"
    assert default.is_placeholder is True
    assert default.usd_ars_oficial == pytest.approx(cfg.AR_FX_PLACEHOLDER_OFICIAL)

    # A caller passing its own rates is neither of the two.
    assert cfg.ArFxConfig(usd_ars_oficial=1100, usd_ars_parallel=1400).rate_source == "manual"

    monkeypatch.setenv("USD_ARS_OFICIAL", "1450")
    from_env = cfg.ArFxConfig()
    assert from_env.rate_source == "env"
    assert from_env.is_placeholder is False
    assert from_env.usd_ars_oficial == pytest.approx(1450.0)
    # ...and the label still describes the values held, not the environment.
    assert cfg.ArFxConfig(usd_ars_oficial=1100, usd_ars_parallel=1400).rate_source == "manual"

    # A malformed override is not an override: placeholders stay, and the label
    # says "placeholder" rather than claiming the environment supplied a rate.
    for bad in ("no-es-un-numero", "0", "-5"):
        monkeypatch.setenv("USD_ARS_OFICIAL", bad)
        typo = cfg.ArFxConfig()
        assert typo.usd_ars_oficial == pytest.approx(cfg.AR_FX_PLACEHOLDER_OFICIAL)
        assert typo.rate_source == "placeholder"


def test_c_f_a_zero_rate_from_the_environment_cannot_reach_the_divisor(monkeypatch):
    """`ar_dual_amounts` raises on rate <= 0, so a bad env would crash two pages."""
    import config as cfg

    monkeypatch.setenv("USD_ARS_OFICIAL", "0")
    monkeypatch.setenv("USD_ARS_PARALLEL", "0")
    fx = cfg.ArFxConfig()
    assert fx.usd_ars_oficial > 0
    assert ar_dual_context(500_000.0, fx_config=fx)["available"] is True


def test_c_g_deflation_raises_the_present_value_instead_of_being_ignored():
    """A negative inflation assumption is rare but must not silently no-op."""
    assert present_value_usd(1000.0, annual_inflation_pct=-2.0, years=10) == pytest.approx(
        1000.0 / (0.98 ** 10)
    )
    with pytest.raises(ValueError):
        present_value_usd(1000.0, annual_inflation_pct=-100.0, years=10)


def test_c_d_the_rendered_line_names_the_basis_the_rate_and_the_doubt():
    line = format_ar_dual_line(
        ar_dual_amounts(
            700_000.0,
            usd_ars_oficial=1000.0,
            usd_ars_parallel=1200.0,
            horizon_years=30,
            usd_inflation_pct=3.0,
            rate_source="placeholder",
        )
    )
    assert "pesos de hoy" in line          # basis stated
    assert "/USD" in line                  # rate travels with the amount
    assert "3.0%" in line and "30 años" in line
    assert line.startswith("⚠️")           # placeholder never reads as a quote
    assert "brecha" not in line
    # And the naive product is nowhere on screen.
    assert f"{700_000 * 1000:,.0f}" not in line


def test_c_e_a_todays_dollars_line_does_not_claim_a_deflation_it_did_not_do():
    line = format_ar_dual_line(
        ar_dual_amounts(500_000.0, usd_ars_oficial=1000.0, rate_source="env", label="meta")
    )
    assert "pesos de hoy" not in line
    assert "inflación" not in line


# --------------------------------------------------------------------------- #
#  D — the page-facing wrapper degrades honestly instead of guessing           #
# --------------------------------------------------------------------------- #

def test_d_a_an_old_snapshot_without_inflation_gets_a_reason_not_a_number():
    ctx = ar_dual_context(700_000.0, fx_config=_FakeFx(), horizon_years=20, usd_inflation_pct=None)
    assert ctx["available"] is False
    assert ctx["dual"] is None
    assert "inflación" in ctx["reason"]


def test_d_b_a_complete_snapshot_renders():
    ctx = ar_dual_context(700_000.0, fx_config=_FakeFx(), horizon_years=20, usd_inflation_pct=3.0)
    assert ctx["available"] is True
    assert ctx["dual"]["ars_oficial"] == pytest.approx(
        reference_pesos(700_000.0, years=20, annual_inflation_pct=3.0, rate=1000.0), abs=1.0
    )
    assert ctx["line"]


def test_d_c_disabled_or_empty_is_not_an_error():
    assert ar_dual_context(700_000.0, fx_config=_FakeFx(enabled=False))["available"] is False
    assert ar_dual_context(0.0, fx_config=_FakeFx())["available"] is False
    assert ar_dual_context(None, fx_config=_FakeFx())["available"] is False


def test_d_d_the_wrapper_carries_the_rate_source_through():
    ctx = ar_dual_context(500_000.0, fx_config=_FakeFx(source="placeholder"))
    assert ctx["dual"]["rate_source"] == "placeholder"
    assert ctx["dual"]["brecha_pct"] is None


# --------------------------------------------------------------------------- #
#  E — page contracts: the defect cannot come back through the UI              #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("page", [SIM_PAGE, PLAN_PAGE], ids=lambda p: p.name)
def test_e_a_no_silent_except_pass_anywhere_on_the_page(page):
    """`except Exception: pass` is how all three defects stayed invisible."""
    tree = ast.parse(page.read_text(encoding="utf-8"))
    silent = [
        h.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for h in node.handlers
        if len(h.body) == 1 and isinstance(h.body[0], ast.Pass)
    ]
    assert not silent, f"{page.name}: silent except-pass at lines {silent}"


@pytest.mark.parametrize("page", [SIM_PAGE, PLAN_PAGE], ids=lambda p: p.name)
def test_e_b_the_pages_go_through_the_guarded_wrapper(page):
    """Calling `ar_dual_amounts` straight from a page skips the horizon guard."""
    src = page.read_text(encoding="utf-8")
    assert "ar_dual_context" in src
    assert not re.search(r"\bar_dual_amounts\s*\(", src), (
        f"{page.name}: use ar_dual_context so the horizon/inflation contract is enforced"
    )


@pytest.mark.parametrize("page", [SIM_PAGE, PLAN_PAGE], ids=lambda p: p.name)
def test_e_c_every_conversion_call_passes_a_horizon_or_is_todays_money(page):
    """A far-away amount reaching the FX layer without its horizon is the bug."""
    tree = ast.parse(page.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "ar_dual_context"
    ]
    assert calls, f"{page.name}: expected at least one ar_dual_context call"
    for call in calls:
        kw = {k.arg for k in call.keywords}
        src_arg = ast.dump(call.args[0]) if call.args else ""
        if "median_terminal" in src_arg or "_med" in src_arg:
            assert {"horizon_years", "usd_inflation_pct"} <= kw, (
                f"{page.name}:{call.lineno}: a Monte Carlo terminal needs both the "
                "horizon and the inflation assumption"
            )


# --------------------------------------------------------------------------- #
#  F — the shipped Simulaciones page, driven for real                          #
# --------------------------------------------------------------------------- #

def _fake_mc(*, horizon: int, median_terminal: float, target: float):
    """A finished Monte Carlo result, so the tab renders without network.

    The page reads `st.session_state["mc_result"]` when the user has not just
    clicked "Ejecutar", which is the seam this uses.
    """
    from portfolio.monte_carlo import MonteCarloResult

    mc = MonteCarloResult(
        n_sims=100,
        horizon_years=horizon,
        initial_value=100_000.0,
        annual_withdrawal=0.0,
        target_value=target,
    )
    mc.median_terminal = median_terminal
    mc.p10_terminal = median_terminal * 0.4
    mc.p25_terminal = median_terminal * 0.7
    mc.p75_terminal = median_terminal * 1.3
    mc.p90_terminal = median_terminal * 1.7
    mc.median_cagr_pct = 6.7
    mc.prob_achieve_target_pct = 70.0
    mc.years = list(range(horizon + 1))
    mc.fan_paths = {
        y: {p: 100_000.0 * ((1 + p / 1000) ** y) for p in (5, 10, 25, 50, 75, 90, 95)}
        for y in range(horizon + 1)
    }
    return mc


def test_f_the_simulaciones_page_prints_pesos_of_today_not_the_spot_product():
    """End-to-end on the page that owns the 20-30 year terminal."""
    from streamlit.testing.v1 import AppTest

    median, target, horizon, inflation = 700_000.0, 500_000.0, 30, 3.0

    at = AppTest.from_file(str(SIM_PAGE), default_timeout=120)
    at.session_state["mc_result"] = _fake_mc(
        horizon=horizon, median_terminal=median, target=target
    )
    at.session_state["horizon_years"] = horizon
    at.session_state["inflation_rate"] = inflation
    at.run()
    assert not at.exception, [str(e)[:400] for e in at.exception]

    text = "\n".join(
        (getattr(e, "value", "") or "")
        for coll in (at.markdown, at.caption, at.info, at.warning, at.success, at.error)
        for e in coll
    )

    # The oracle, on the shipped surface: no USD-at-year-30 × today's rate.
    naive = median * 1000.0                       # AR_FX placeholder oficial
    assert f"{naive:,.0f}" not in text

    # What it prints instead is the deflated figure, labelled.
    expected = median / (1 + inflation / 100) ** horizon * 1000.0
    assert f"{expected:,.0f}" in text
    assert "pesos de hoy" in text
    assert "tasa de referencia (no es cotización)" in text

    # The target lives on the SAME basis as the median — the sidebar calls it
    # "valor objetivo al final del horizonte" and `prob_achieve_target_pct`
    # scores it against the nominal terminals. Showing one deflated and the
    # other at spot would put a fake shortfall next to a 70 % probability.
    target_line = next(l for l in text.split("\n") if l.startswith("**Tu meta:**"))
    expected_target = target / (1 + inflation / 100) ** horizon * 1000.0
    assert f"{expected_target:,.0f}" in target_line
    assert f"{target * 1000.0:,.0f}" not in target_line
    assert "pesos de hoy" in target_line
    # ...and the ratio the user reads off the two lines survives the conversion.
    median_line = next(l for l in text.split("\n") if l.startswith("**Mediana proyectada:**"))
    assert median_line and expected / expected_target == pytest.approx(median / target)


def test_f_b_a_zero_inflation_assumption_is_an_answer_not_a_gap():
    """The slider starts at 0 %; choosing it must not read as "no lo dijiste"."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(SIM_PAGE), default_timeout=120)
    at.session_state["mc_result"] = _fake_mc(horizon=30, median_terminal=700_000.0, target=0.0)
    at.session_state["horizon_years"] = 30
    at.session_state["inflation_rate"] = 0.0
    at.run()
    assert not at.exception, [str(e)[:400] for e in at.exception]

    text = "\n".join(
        (getattr(e, "value", "") or "")
        for coll in (at.markdown, at.caption, at.info, at.warning, at.success, at.error)
        for e in coll
    )
    assert "no hay supuesto de inflación" not in text
    # With i = 0 the nominal figure IS today's money, so it converts at spot.
    assert f"{700_000 * 1000.0:,.0f}" in text


def test_f_c_an_unknown_horizon_is_not_todays_money():
    """`mc_summary` without `horizon_years` must not fall back to spot."""
    ctx = ar_dual_context(
        700_000.0, fx_config=_FakeFx(), horizon_years=None, usd_inflation_pct=3.0
    )
    assert ctx["available"] is False
    assert "horizonte" in ctx["reason"]
    # Zero, on the other hand, is a real statement about the amount.
    assert ar_dual_context(700_000.0, fx_config=_FakeFx(), horizon_years=0)["available"] is True


def test_f_d_a_zero_inflation_assumption_reaches_the_conversion():
    ctx = ar_dual_context(
        700_000.0, fx_config=_FakeFx(), horizon_years=30, usd_inflation_pct=0.0
    )
    assert ctx["available"] is True
    assert ctx["dual"]["ars_oficial"] == pytest.approx(700_000.0 * 1000.0)
