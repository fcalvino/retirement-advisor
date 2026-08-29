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

Pero el arreglo **no es uniformemente conservador**, y descubrirlo costó un test
que afirmaba lo contrario. Con gasto exógeno (``fixed_real``) el total del año
es un número dado y adelantarlo sólo puede dejar menos capital. Con gasto
endógeno (``constant_pct``, ``guardrails``) el importe sale de la riqueza, y
repartir el pago obliga a decidir el presupuesto al **inicio** del año en vez
del final —no se paga en enero con una decisión de diciembre—. En un mercado
que sube, decidir antes da un importe menor y eso empuja el pozo para arriba.
Cuál de los dos términos gana depende de la dirección del mercado.

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


class TestGastarTodosLosMesesCambiaElPozo:
    """El efecto NO es uniformemente conservador, y eso hay que decirlo.

    Con **gasto exógeno** (``fixed_real``, el importe lo fija el jubilado) el
    total del año no depende del mercado, así que adelantarlo sólo puede dejar
    menos capital: es aritmética.

    Con **gasto endógeno** (``constant_pct``, ``guardrails``, el importe sale de
    la riqueza) cambian dos cosas a la vez. Se reparte el pago —que baja el
    pozo— y el presupuesto pasa a decidirse al **inicio** del año en vez del
    final, porque no se puede pagar en enero con una decisión de diciembre. En
    un mercado que sube, decidir antes da un importe menor, y ese término empuja
    el pozo para arriba. Cuál gana depende de la dirección del mercado.
    """

    def test_con_gasto_exogeno_el_pozo_final_baja(self, cadencia):
        """El caso donde la dirección es demostrable sin supuestos: el total
        anual es el mismo número, sólo se adelanta."""
        market = _mercado(52 * 20, weekly_growth=0.0015)
        strat = WithdrawalStrategy.fixed_real(40_000.0)

        cadencia(1)
        anual = apply_withdrawal_strategy(market.copy(), 1_000_000.0, strat, 52 * 20)
        cadencia(12)
        mensual = apply_withdrawal_strategy(market.copy(), 1_000_000.0, strat, 52 * 20)

        assert mensual[0, -1] < anual[0, -1], (
            f"mensual dejó {mensual[0, -1]:.4f} y anual {anual[0, -1]:.4f} — con el "
            f"total del año fijo, adelantarlo no puede dejar MÁS pozo"
        )

    @pytest.mark.parametrize("build", [
        lambda: WithdrawalStrategy.constant_pct(0.04),
        lambda: WithdrawalStrategy.guardrails(0.04),
    ])
    def test_con_gasto_endogeno_el_presupuesto_se_decide_al_inicio(self, cadencia, build):
        """La semántica que el reparto obliga, fijada de forma directa.

        El presupuesto del año 1 tiene que salir de la riqueza al **empezar** el
        año, no de la del final. Con un mercado que crece 0,3 %/semana la
        riqueza de la semana 52 es ~17 % mayor que la de la semana 4, así que
        las dos lecturas dan importes bien distintos y el test las distingue.
        """
        market = _mercado(52 * 3, weekly_growth=0.003)
        cadencia(12)
        salidas = _retiros_por_semana(
            apply_withdrawal_strategy(market.copy(), 1_000_000.0, build(), 52 * 3), market
        )
        total_ano1 = salidas[:52].sum()
        riqueza_inicio = market[0, 4]        # primera cuota
        riqueza_fin = market[0, 52]

        cerca_del_inicio = abs(total_ano1 - 0.04 * riqueza_inicio)
        cerca_del_fin = abs(total_ano1 - 0.04 * riqueza_fin)
        assert cerca_del_inicio < cerca_del_fin, (
            f"el presupuesto del año 1 ({total_ano1:.5f}) se parece más al 4 % de "
            f"la riqueza de fin de año ({0.04 * riqueza_fin:.5f}) que al de "
            f"inicio ({0.04 * riqueza_inicio:.5f}): se sigue decidiendo tarde"
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

    def test_el_pozo_agotado_queda_en_cero_EXACTO(self, cadencia):
        """No «por debajo de epsilon»: cero exacto.

        La primera versión de este PR recortaba cada cuota contra la riqueza
        disponible. Parecía prudente y era peor: `cash_flow_units` pisa las
        unidades a cero, así que pedir de más deja el pozo en cero exacto,
        mientras que recortar dejaba una miga de 5e-19. El docstring del
        primitivo ya lo decía — «absorption is a property of the algebra rather
        than of a defensive branch» (auditoría D2) — y el recorte volvía a meter
        la rama defensiva.

        Lo destapó de casualidad un test de identidad de bits en otro archivo.
        Acá queda como la propiedad que es, con la comparación que la distingue:
        `== 0.0`, no `<= 1e-9`.
        """
        # Hace falta un mercado **irregular**: sobre una curva suave la división
        # `riqueza / mercado` da exacta por casualidad y el recorte no se nota.
        # El residuo vive donde los valores no son redondos, que es todo mercado
        # real. Semilla fija — nada de `hash()`, que está aleatorizado por proceso.
        rng = np.random.default_rng(0)
        n_weeks = 20 * 52
        market = np.cumprod(1 + rng.normal(0.001, 0.02, size=(200, n_weeks)), axis=1)
        market = np.concatenate([np.ones((200, 1)), market], axis=1)

        cadencia(12)
        paths = apply_withdrawal_strategy(
            market.copy(), 100_000.0,
            WithdrawalStrategy.fixed_real(4_000.0), n_weeks, inflation_rate=0.03,
        )

        agotados = 0
        for fila in paths:
            muerto = fila <= 1e-9
            if not muerto.any():
                continue
            agotados += 1
            cola = fila[int(np.argmax(muerto)):]
            assert np.all(cola == 0.0), (
                f"tras agotarse el pozo quedó en {cola.max():.3g} en vez de cero "
                f"exacto: hay un recorte defensivo donde debería estar el álgebra"
            )
        assert agotados > 0, "el escenario dejó de agotar pozos"

    def test_la_cadencia_que_se_shipea_es_mensual(self):
        """Un jubilado gasta todos los meses. Si alguien vuelve a poner 1 por
        defecto, que sea un acto consciente y no un merge."""
        assert MONTE_CARLO.withdrawal_periods_per_year == 12

    def test_un_pozo_inicial_de_cero_sigue_siendo_degenerado(self, cadencia):
        cadencia(12)
        market = _mercado(52 * 5)
        out = apply_withdrawal_strategy(
            market.copy(), 0.0, WithdrawalStrategy.fixed_real(1_000.0), 52 * 5
        )
        assert np.all(out == 0.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
