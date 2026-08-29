"""Oracle for U4-1c — decidir anual, pagar en doceavos.

U4-1 mensualizó los **aportes** y dejó los **retiros** anuales a propósito: la
estrategia de guardrails *es* una revisión anual, así que pagar mensual mientras
se decide anual era una pregunta de diseño aparte. Esta es esa pregunta.

Un jubilado gasta todos los meses. El motor lo hacía gastar una vez al año, y de
dos maneras que se suman:

  * **el lump de diciembre** — el año entero de gasto sale junto al final, así
    que ese dinero compone doce meses de más antes de irse;
  * **el año gratis** — ``weeks = [yr * 52 for yr in 1..N]`` pone el primer
    retiro en la **semana 52**, o sea que el primer año de la jubilación
    transcurre entero sin que salga un peso. Eso no estaba en la fila y es la
    mitad más grande del efecto.

Las dos empujan en la misma dirección: **sobrestiman el pozo que sobrevive**.

Lo que este oráculo NO permite es arreglarlo convirtiendo la estrategia en otra
cosa. La decisión sigue siendo anual —los guardrails son una revisión anual, y
recalcularlos doce veces al año sería un método distinto, no el mismo método
mejor pagado—, así que dentro de un año los doce pagos tienen que ser **iguales**
y sólo pueden cambiar al cruzar el límite del año.

Sin red, sin Streamlit.
"""

from __future__ import annotations

import numpy as np
import pytest

from config import MONTE_CARLO
from portfolio.decumulation import (
    WithdrawalStrategy,
    apply_withdrawal_strategy,
)


@pytest.fixture
def cadencia():
    """Mutar el singleton no puede filtrarse al test siguiente."""
    saved = MONTE_CARLO.withdrawal_periods_per_year
    yield lambda n: setattr(MONTE_CARLO, "withdrawal_periods_per_year", n)
    MONTE_CARLO.withdrawal_periods_per_year = saved


def _mercado(n_weeks: int, weekly_growth: float = 0.0, n_sims: int = 1) -> np.ndarray:
    """Curva de mercado determinística: sin ruido, el efecto que se mide es el
    de la cadencia y nada más."""
    curva = (1.0 + weekly_growth) ** np.arange(n_weeks + 1)
    return np.tile(curva, (n_sims, 1))


def _retiros_por_semana(paths: np.ndarray, market: np.ndarray) -> np.ndarray:
    """Reconstruye lo que salió cada semana, en unidades de riqueza.

    ``paths`` es riqueza y ``market`` el índice intacto, así que las *unidades*
    en cada semana son ``paths / market``; lo que salió es la caída de unidades
    valuada al mercado de esa semana. Derivado de la definición, no leído del
    código que produce el resultado.
    """
    units = paths / market
    salidas = -(np.diff(units, axis=1)) * market[:, 1:]
    return np.where(np.abs(salidas) < 1e-9, 0.0, salidas)[0]


# --------------------------------------------------------------------------- #
#  La dirección del arreglo es demostrable                                     #
# --------------------------------------------------------------------------- #


class TestGastarTodosLosMesesDejaMenosPozo:

    @pytest.mark.parametrize("kind,build", [
        ("fixed_real", lambda: WithdrawalStrategy.fixed_real(40_000.0)),
        ("constant_pct", lambda: WithdrawalStrategy.constant_pct(0.04)),
        ("guardrails", lambda: WithdrawalStrategy.guardrails(0.04)),
    ])
    def test_el_pozo_final_baja_en_las_tres_estrategias(self, cadencia, kind, build):
        """El mismo gasto anual, repartido, deja menos capital — porque el dinero
        que sale en enero no compone los once meses siguientes.

        Con mercado plano la diferencia sería cero, así que el test corre sobre
        un mercado que crece: es la única condición donde la cadencia importa, y
        por eso es donde hay que medirla.
        """
        market = _mercado(52 * 20, weekly_growth=0.0015)

        cadencia(1)
        anual = apply_withdrawal_strategy(market.copy(), 1_000_000.0, build(), 52 * 20)
        cadencia(12)
        mensual = apply_withdrawal_strategy(market.copy(), 1_000_000.0, build(), 52 * 20)

        assert mensual[0, -1] < anual[0, -1], (
            f"{kind}: mensual dejó {mensual[0, -1]:.4f} y anual {anual[0, -1]:.4f} — "
            f"repartir el gasto no puede dejar MÁS pozo"
        )

    def test_el_primer_ano_deja_de_ser_gratis(self, cadencia):
        """El defecto que la fila no menciona: con cadencia anual no sale un peso
        hasta la semana 52, así que el primer año de jubilación es gratis."""
        market = _mercado(52 * 3, weekly_growth=0.0)
        strat = WithdrawalStrategy.fixed_real(40_000.0)

        cadencia(1)
        anual = _retiros_por_semana(
            apply_withdrawal_strategy(market.copy(), 1_000_000.0, strat, 52 * 3), market
        )
        cadencia(12)
        mensual = _retiros_por_semana(
            apply_withdrawal_strategy(market.copy(), 1_000_000.0, strat, 52 * 3), market
        )

        assert anual[:51].sum() == pytest.approx(0.0, abs=1e-9), (
            "con cadencia anual algo salía antes de la semana 52"
        )
        assert mensual[:51].sum() > 0, "el jubilado sigue sin gastar en su primer año"


# --------------------------------------------------------------------------- #
#  Sólo cambia el reparto, no el total                                         #
# --------------------------------------------------------------------------- #


class TestElTotalDelAnoNoSeMueve:

    def test_los_doce_pagos_suman_el_mismo_ano(self, cadencia):
        """Si el total anual cambiara, esto no sería un arreglo de cadencia sino
        un recorte encubierto del gasto."""
        market = _mercado(52 * 3, weekly_growth=0.0)          # plano: aísla el total
        strat = WithdrawalStrategy.fixed_real(50_000.0)

        cadencia(1)
        anual = _retiros_por_semana(
            apply_withdrawal_strategy(market.copy(), 1_000_000.0, strat, 52 * 3), market
        )
        cadencia(12)
        mensual = _retiros_por_semana(
            apply_withdrawal_strategy(market.copy(), 1_000_000.0, strat, 52 * 3), market
        )
        for año in range(3):
            ini, fin = año * 52, (año + 1) * 52
            assert mensual[ini:fin].sum() == pytest.approx(
                anual[ini:fin].sum(), rel=1e-9
            ), f"año {año + 1}: el total anual se movió"


# --------------------------------------------------------------------------- #
#  La decisión sigue siendo anual                                              #
# --------------------------------------------------------------------------- #


class TestSeDecideUnaVezPorAnoYSePagaEnDoceavos:
    """La restricción que separa este arreglo de un método distinto."""

    @pytest.mark.parametrize("build", [
        lambda: WithdrawalStrategy.constant_pct(0.05),
        lambda: WithdrawalStrategy.guardrails(0.05),
    ])
    def test_los_doce_pagos_de_un_ano_son_iguales(self, cadencia, build):
        """Un guardrail que se recalcula doce veces al año es otro método.

        Con un mercado que se mueve, una estrategia dependiente del valor daría
        doce importes distintos si decidiera mensualmente. Tienen que ser doce
        importes **iguales**: se decidió una vez, se paga en doceavos.
        """
        market = _mercado(52 * 4, weekly_growth=0.003)
        cadencia(12)
        salidas = _retiros_por_semana(
            apply_withdrawal_strategy(market.copy(), 1_000_000.0, build(), 52 * 4), market
        )
        for año in range(4):
            pagos = salidas[año * 52:(año + 1) * 52]
            pagos = pagos[pagos > 0]
            assert len(pagos) == 12, f"año {año + 1}: {len(pagos)} pagos, no 12"
            assert np.allclose(pagos, pagos[0], rtol=1e-9), (
                f"año {año + 1}: los pagos no son iguales — se está decidiendo "
                f"más de una vez al año: {pagos}"
            )

    def test_entre_anos_el_importe_si_cambia(self, cadencia):
        """Anti-cheat: fijar los pagos dentro del año no puede congelar la
        estrategia. La revisión anual tiene que seguir moviendo el gasto."""
        market = _mercado(52 * 4, weekly_growth=0.003)
        cadencia(12)
        salidas = _retiros_por_semana(
            apply_withdrawal_strategy(
                market.copy(), 1_000_000.0, WithdrawalStrategy.constant_pct(0.05), 52 * 4
            ),
            market,
        )
        por_año = [salidas[a * 52:(a + 1) * 52][salidas[a * 52:(a + 1) * 52] > 0][0]
                   for a in range(4)]
        assert len({round(p, 9) for p in por_año}) > 1, (
            f"el importe nunca cambió entre años: {por_año}"
        )


# --------------------------------------------------------------------------- #
#  La salida de emergencia, y lo que no se puede romper                        #
# --------------------------------------------------------------------------- #


class TestLoQueNoPuedeRomperse:

    def test_con_la_config_en_uno_el_motor_es_byte_identico(self, cadencia):
        """Misma garantía que dio U4-1 para los aportes: la cadencia vieja sigue
        siendo reproducible exactamente, así que un plan viejo se puede recrear."""
        market = _mercado(52 * 10, weekly_growth=0.002, n_sims=3)
        strat = WithdrawalStrategy.guardrails(0.045)

        cadencia(1)
        a = apply_withdrawal_strategy(market.copy(), 500_000.0, strat, 52 * 10)
        cadencia(1)
        b = apply_withdrawal_strategy(market.copy(), 500_000.0, strat, 52 * 10)
        assert np.array_equal(a, b)

        semanas_con_flujo = (np.abs(np.diff(a / market, axis=1)) > 1e-12).sum(axis=1)
        assert semanas_con_flujo[0] == 10, (
            f"con la config en 1 hubo {semanas_con_flujo[0]} flujos en 10 años"
        )

    def test_la_ruina_sigue_siendo_absorbente(self, cadencia):
        """Auditoría D2: un pozo vaciado por el gasto queda vacío pase lo que
        pase con el mercado. Repartir el gasto no puede resucitarlo."""
        market = _mercado(52 * 30, weekly_growth=0.004)
        cadencia(12)
        paths = apply_withdrawal_strategy(
            market.copy(), 100_000.0, WithdrawalStrategy.fixed_real(90_000.0), 52 * 30
        )
        w = paths[0]
        primera_cero = np.argmax(w <= 1e-9)
        assert w[primera_cero] <= 1e-9
        assert np.all(w[primera_cero:] <= 1e-9), "el pozo revivió después de agotarse"

    def test_un_pozo_inicial_de_cero_sigue_siendo_degenerado(self, cadencia):
        cadencia(12)
        market = _mercado(52 * 5)
        out = apply_withdrawal_strategy(
            market.copy(), 0.0, WithdrawalStrategy.fixed_real(1_000.0), 52 * 5
        )
        assert np.all(out == 0.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
