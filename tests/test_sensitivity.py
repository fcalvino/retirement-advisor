"""Tests for the sensitivity & scenario lab (Fase H.3).

Uses a deterministic fake ``run_fn`` so the engine is exercised fully offline
(no Monte Carlo, no network). The fake encodes the expected directional
relationships (more inflation/drags/vol → worse; more return → better).
"""

from __future__ import annotations

from types import SimpleNamespace

from config import SENSITIVITY
from portfolio.sensitivity import (
    METRIC_KEYS,
    SensitivityResult,
    run_sensitivity,
    tornado_rows,
)


def _fake_run(params: dict):
    """Deterministic, monotone surrogate for a MonteCarloResult."""
    infl = float(params.get("withdrawal_growth_rate", 0.0) or 0.0)
    drag = float(params.get("drags_total_pct", 0.0) or 0.0)
    rs = float(params.get("return_scale", 1.0) or 1.0)
    vs = float(params.get("vol_scale", 1.0) or 1.0)
    h = float(params.get("horizon_years", 20) or 20)

    median = 500_000.0 * rs - infl * 1_000_000.0 - drag * 50_000.0 + (h - 20) * 5_000.0
    p10 = median - vs * 100_000.0
    p90 = median + vs * 100_000.0
    ruin = max(0.0, 10.0 + infl * 100.0 + drag * 5.0 - (rs - 1.0) * 50.0 + (vs - 1.0) * 40.0)
    return SimpleNamespace(
        p10_terminal=p10, median_terminal=median, p90_terminal=p90, prob_ruin_pct=ruin
    )


def _base():
    return {
        "withdrawal_growth_rate": 0.03,
        "drags_total_pct": 0.25,
        "return_scale": 1.0,
        "vol_scale": 1.0,
        "horizon_years": 20,
        "longevity_years": 20,
    }


# ------------------------------------------------------------------ #
#  Structure / base                                                    #
# ------------------------------------------------------------------ #

class TestStructure:
    def test_returns_result_with_base_and_four_factors(self):
        res = run_sensitivity(_fake_run, _base())
        assert isinstance(res, SensitivityResult)
        assert set(res.base.keys()) == set(METRIC_KEYS)
        assert len(res.factors) == 4
        assert len(res.scenarios) == 4

    def test_base_params_not_mutated(self):
        base = _base()
        snapshot = dict(base)
        run_sensitivity(_fake_run, base)
        assert base == snapshot

    def test_base_metrics_match_direct_run(self):
        res = run_sensitivity(_fake_run, _base())
        direct = _fake_run(_base())
        assert res.base["median_terminal"] == direct.median_terminal


# ------------------------------------------------------------------ #
#  Factor directionality                                               #
# ------------------------------------------------------------------ #

class TestFactors:
    def _factor(self, res, key):
        return next(f for f in res.factors if f.key == key)

    def test_more_fees_lowers_terminal(self):
        res = run_sensitivity(_fake_run, _base())
        fees = self._factor(res, "fees")
        # high = more drag = lower median
        assert fees.high["median_terminal"] < fees.low["median_terminal"]

    def test_higher_return_raises_terminal(self):
        res = run_sensitivity(_fake_run, _base())
        rr = self._factor(res, "real_return")
        assert rr.high["median_terminal"] > rr.low["median_terminal"]

    def test_higher_inflation_raises_ruin(self):
        res = run_sensitivity(_fake_run, _base())
        infl = self._factor(res, "inflation")
        assert infl.high["prob_ruin_pct"] > infl.low["prob_ruin_pct"]

    def test_fee_floor_never_negative(self):
        # Base drag 0.1 with delta 0.30 → low would be -0.20, must floor at 0.
        base = _base()
        base["drags_total_pct"] = 0.1
        res = run_sensitivity(_fake_run, base)
        fees = self._factor(res, "fees")
        # At the floor (drag=0) the terminal is the highest possible for this factor.
        assert fees.low["median_terminal"] == _fake_run({**base, "drags_total_pct": 0.0}).median_terminal


# ------------------------------------------------------------------ #
#  Tornado ordering                                                    #
# ------------------------------------------------------------------ #

class TestTornado:
    def test_rows_sorted_by_swing_desc(self):
        res = run_sensitivity(_fake_run, _base())
        rows = tornado_rows(res)
        swings = [r["swing"] for r in rows]
        assert swings == sorted(swings, reverse=True)
        assert len(rows) == 4

    def test_rows_carry_base_and_labels(self):
        res = run_sensitivity(_fake_run, _base())
        row = tornado_rows(res, metric="median_terminal")[0]
        assert "base" in row and row["base"] == res.base["median_terminal"]
        assert row["low_label"] and row["high_label"]


# ------------------------------------------------------------------ #
#  Scenarios                                                           #
# ------------------------------------------------------------------ #

class TestScenarios:
    def _scn(self, res, key):
        return next(s for s in res.scenarios if s.key == key)

    def test_full_drags_scenario_lowers_terminal(self):
        res = run_sensitivity(_fake_run, _base())
        sc = self._scn(res, "drags_full")
        assert sc.deltas["median_terminal"] < 0
        assert sc.metrics["median_terminal"] < res.base["median_terminal"]

    def test_adverse_market_lowers_p10(self):
        res = run_sensitivity(_fake_run, _base())
        sc = self._scn(res, "adverse_market")
        assert sc.deltas["p10_terminal"] < 0

    def test_live_longer_changes_outcome(self):
        res = run_sensitivity(_fake_run, _base())
        sc = self._scn(res, "live_longer")
        # Horizon +5 in the surrogate raises terminal; delta is non-zero either way.
        assert sc.deltas["median_terminal"] != 0

    def test_can_disable_scenarios(self):
        res = run_sensitivity(_fake_run, _base(), include_scenarios=False)
        assert res.scenarios == []


# ------------------------------------------------------------------ #
#  Config wiring                                                       #
# ------------------------------------------------------------------ #

def test_uses_config_magnitudes():
    # Verify the inflation factor moves by exactly SENSITIVITY.inflation_delta_pct.
    res = run_sensitivity(_fake_run, _base())
    infl = next(f for f in res.factors if f.key == "inflation")
    base = _base()
    expected_high = _fake_run(
        {**base, "withdrawal_growth_rate": 0.03 + SENSITIVITY.inflation_delta_pct / 100.0}
    ).median_terminal
    assert infl.high["median_terminal"] == expected_high


# ------------------------------------------------------------------ #
#  U4-3 — "no aplica" no es lo mismo que "medí y da cero"              #
# ------------------------------------------------------------------ #

def _run_sin_indexar(params: dict):
    """Surrogate de un plan cuyo gasto NO se indexa por inflación.

    Es el caso real de ``constant_pct``: la estrategia toma un % del pozo
    actual, así que ``decide`` nunca lee ``inflation_rate``
    (``portfolio/decumulation.py:389-392``). Medido sobre 5 tickers cacheados,
    el swing de la palanca "Inflación" da **0,00 exacto** con retiros activos —
    justo el caso que la fila U4-3 daba por imposible.
    """
    return _fake_run({**params, "withdrawal_growth_rate": 0.0})


class TestPalancaQueNoAplica:
    """Una barra de ancho cero afirma que se midió; hay que poder desmentirlo.

    El tornado dibuja ``x=[high - low]``. Cuando la palanca no toca el plan eso
    es una barra invisible junto a su etiqueta, y el pie del gráfico dice "la
    barra más larga = el supuesto que más mueve tu resultado". Es decir: el
    usuario lee "la inflación no mueve mi plan", que es una afirmación, no la
    ausencia de una.

    El criterio lo mide el motor y no lo adivina la UI: la palanca no aplica
    cuando mover el supuesto a su valor bajo y a su alto deja **idénticas las
    cuatro métricas**. No hay que enumerar qué método de retiro indexa el gasto,
    y sigue siendo correcto cuando mañana se agregue otro.
    """

    def _factor(self, res, key):
        return next(f for f in res.factors if f.key == key)

    def test_una_palanca_que_no_mueve_nada_no_aplica(self):
        res = run_sensitivity(_run_sin_indexar, _base())
        infl = self._factor(res, "inflation")
        assert infl.low == infl.high, "el surrogate no reprodujo el caso medido"
        assert infl.applies is False, (
            "la palanca no movió ninguna métrica y el tornado la presenta igual "
            "que a las que sí midió: una barra de ancho cero se lee como un "
            "resultado, no como «este supuesto no toca tu plan»"
        )

    def test_una_palanca_que_mueve_algo_si_aplica(self):
        res = run_sensitivity(_run_sin_indexar, _base())
        for key in ("fees", "real_return", "volatility"):
            assert self._factor(res, key).applies is True, (
                f"la palanca {key} sí mueve el resultado y quedó marcada como "
                f"inaplicable"
            )

    def test_applies_mira_las_cuatro_metricas_no_la_graficada(self):
        """El caso que hay que acertar para no marcar de más.

        Un plan solvente da ``prob_ruin_pct = 0`` en las cuatro palancas. Si el
        criterio mirara sólo la métrica elegida en el selectbox, las cuatro
        quedarían "no aplica" con esa métrica seleccionada — y tres de ellas sí
        mueven el plan. El criterio es sobre todo ``METRIC_KEYS``.
        """
        def _run_sin_ruina(params: dict):
            r = _fake_run(params)
            r.prob_ruin_pct = 0.0
            return r

        res = run_sensitivity(_run_sin_ruina, _base())
        for f in res.factors:
            assert f.low["prob_ruin_pct"] == f.high["prob_ruin_pct"] == 0.0
        assert all(f.applies for f in res.factors), (
            "una ruina plana en 0 volvió inaplicables a palancas que mueven el "
            "capital terminal"
        )

    def test_tornado_rows_propaga_applies(self):
        res = run_sensitivity(_run_sin_indexar, _base())
        rows = tornado_rows(res)
        assert all("applies" in r for r in rows), (
            "la fila que consume la UI no lleva el dato, así que la pantalla "
            "no puede distinguir un cero medido de un supuesto que no aplica"
        )
        infl = next(r for r in rows if r["key"] == "inflation")
        assert infl["applies"] is False
        assert infl["swing"] == 0.0

    def test_un_escenario_sin_efecto_tampoco_aplica(self):
        """Misma mentira, otra superficie: la tabla muestra «Δ vs base $0»."""
        res = run_sensitivity(_run_sin_indexar, _base())
        hot = next(s for s in res.scenarios if s.key == "inflation_hot")
        assert all(v == 0 for v in hot.deltas.values())
        assert hot.applies is False, (
            "el escenario no cambió ninguna métrica y la tabla lo reporta como "
            "un delta de cero medido"
        )
        otros = [s for s in res.scenarios if s.key != "inflation_hot"]
        assert all(s.applies for s in otros)
