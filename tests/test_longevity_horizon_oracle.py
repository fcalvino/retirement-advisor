"""Oracle for U4-4 — el producto afirma una longevidad que nunca simuló.

`decumulation_metrics` recorta con ``cap_week = min(longevity * 52, n_cols - 1)``.
Cuando la longevidad pedida supera el horizonte simulado gana el segundo, así que
los años de más no existen — pero la copy los nombra igual.

## No es un caso borde: es el estado por defecto

    MONTE_CARLO.default_horizon_years   = 20
    WITHDRAWAL.default_longevity_years  = 30

y el selector de horizonte arranca en 20 mientras el widget de longevidad arranca
en 30 y acepta hasta 60. **Sin que nadie toque nada**, el producto ya dice «tu
ingreso dura los 30 años en X % de los escenarios» habiendo simulado 20.

Medido con horizonte 20 y retiro fijo de 55 000 sobre un pozo de 1 000 000:

    longevidad pedida    10      20      30      45      60
    sostiene           100,00  97,77   97,77   97,77   97,77
    reporta longevity      10      20      30      45      60

El número es **idéntico** de 20 en adelante porque esos años no se simulan, y el
resultado reporta la longevidad **pedida**, no la medida, así que cada consumidor
—la página de Plan, el PDF, los prompts— repite la afirmación.

El sesgo tiene una dirección: los años que no se simulan son justo aquellos en
que el pozo está más chico, así que truncar es **sistemáticamente optimista**.

## Por qué se extiende en vez de negarse a contestar

El repo tiene precedente de decir «no sé» en vez de inventar (U3-1, U2-4, U5-14,
U7-3), y acá no aplica: no falta un dato, sobra un recorte. El usuario hizo una
pregunta bien planteada —«¿me dura hasta los 95?»— y el motor puede contestarla.
Negarse dejaría además la configuración por defecto mostrando «desconocido» en
una métrica central.

Lo que **no** puede pasar es que extender mueva los números de riqueza: el
terminal, el fan chart y el CAGR siguen siendo los del horizonte de proyección.
Sólo las métricas de decumulación miran la ventana larga.

Sin red, sin Streamlit.
"""

from __future__ import annotations

import numpy as np
import pytest

from config import MONTE_CARLO, WITHDRAWAL
from portfolio.decumulation import WithdrawalStrategy

SYMS = ["SPY", "BND", "KO", "JNJ", "PG"]
WEIGHTS = np.array([0.4, 0.3, 0.1, 0.1, 0.1])


def _run(*, horizon, longevity, n_sims=2000, annual=55_000.0, seed=42):
    from portfolio.monte_carlo import MonteCarloSimulator

    return MonteCarloSimulator(SYMS, weights=WEIGHTS, seed=seed).run(
        horizon_years=horizon,
        n_sims=n_sims,
        initial_value=1_000_000.0,
        withdrawal_strategy=WithdrawalStrategy.fixed_real(annual),
        longevity_years=longevity,
    )


# --------------------------------------------------------------------------- #
#  El defecto: pedir más años no cambiaba nada                                 #
# --------------------------------------------------------------------------- #


class TestPedirMasAniosCambiaLaRespuesta:

    def test_una_longevidad_mayor_no_puede_dar_la_misma_probabilidad(self):
        """El defecto, aislado. Con el mismo horizonte de proyección, pedir 40
        años de retiro en vez de 20 tiene que dar una probabilidad **menor**:
        hay veinte años más en los que el pozo puede agotarse."""
        corto = _run(horizon=20, longevity=20)
        largo = _run(horizon=20, longevity=40)

        assert largo.prob_sustain_real_pct < corto.prob_sustain_real_pct, (
            f"pedir 40 años dio {largo.prob_sustain_real_pct:.2f} % y pedir 20 dio "
            f"{corto.prob_sustain_real_pct:.2f} % — los veinte años extra no se "
            f"están simulando"
        )

    def test_la_probabilidad_baja_de_forma_ESTRICTA_pasado_el_horizonte(self):
        """Propiedad, no caso: más años de retiro nunca pueden hacer más probable
        que el dinero alcance.

        La comparación es **estricta** a propósito. Con el recorte viejo las
        probabilidades de 25, 35 y 45 son idénticas entre sí, y un
        ``sorted(reverse=True)`` las acepta como orden válido — el test pasaría
        sobre el código roto. Empatar es exactamente el síntoma.
        """
        probs = [_run(horizon=20, longevity=lon).prob_sustain_real_pct
                 for lon in (25, 35, 45)]
        assert all(a > b for a, b in zip(probs, probs[1:])), (
            f"las probabilidades no bajan al pedir más años: {probs} — si hay "
            f"empates, esos años no se están simulando"
        )

    def test_la_longevidad_reportada_es_la_que_se_midio(self):
        """Reportaba la pedida aunque hubiera medido otra cosa, y cada consumidor
        —Plan, PDF, prompts— repetía esa cifra."""
        r = _run(horizon=20, longevity=45)
        assert r.longevity_years == 45

    def test_el_ano_de_agotamiento_puede_caer_despues_del_horizonte(self):
        """Si el pozo se agota en el año 28 de un retiro de 40, la fecha tiene
        que poder decirlo — antes el máximo expresable era el horizonte."""
        r = _run(horizon=20, longevity=40, annual=80_000.0)
        assert r.expected_depletion_year > 20, (
            f"el agotamiento salió en el año {r.expected_depletion_year}, que es "
            f"el techo viejo: la ventana sigue recortada al horizonte"
        )


# --------------------------------------------------------------------------- #
#  Lo que no puede moverse                                                     #
# --------------------------------------------------------------------------- #


class TestExtenderNoMueveLosNumerosDeRiqueza:
    """Las métricas de riqueza son del horizonte de PROYECCIÓN. Sólo las de
    decumulación miran la ventana larga."""

    @pytest.mark.parametrize("longevity", [10, 20, 30, 45])
    def test_el_terminal_no_depende_de_la_longevidad(self, longevity):
        """El capital al final del horizonte es el mismo se pida la longevidad
        que se pida: son dos preguntas distintas sobre la misma simulación."""
        base = _run(horizon=20, longevity=20)
        otro = _run(horizon=20, longevity=longevity)
        assert otro.median_terminal == pytest.approx(base.median_terminal, rel=1e-12)
        assert otro.p10_terminal == pytest.approx(base.p10_terminal, rel=1e-12)
        assert otro.p90_terminal == pytest.approx(base.p90_terminal, rel=1e-12)

    def test_el_fan_chart_llega_hasta_el_horizonte_y_no_mas(self):
        r = _run(horizon=20, longevity=45)
        assert max(r.years) == 20, (
            f"el fan chart llega al año {max(r.years)}: se está dibujando la "
            f"ventana de longevidad en vez del horizonte de proyección"
        )

    @pytest.mark.parametrize("metrica", [
        "median_cagr_pct", "sorr_early_drawdown_pct", "median_max_drawdown_pct",
        "prob_achieve_target_pct", "prob_ruin_pct",
    ])
    def test_las_demas_metricas_tampoco_se_mueven(self, metrica):
        base = _run(horizon=20, longevity=20)
        otro = _run(horizon=20, longevity=45)
        assert getattr(otro, metrica) == pytest.approx(getattr(base, metrica), rel=1e-12), (
            f"{metrica} cambió al pedir más longevidad, y no debería: es una "
            f"métrica del horizonte de proyección"
        )

    def test_con_longevidad_menor_o_igual_el_motor_es_byte_identico(self):
        """La garantía que hace revisable este cambio: si la longevidad no supera
        el horizonte, nada de lo que el motor producía se mueve."""
        a = _run(horizon=20, longevity=15)
        b = _run(horizon=20, longevity=15)
        assert a.prob_sustain_real_pct == b.prob_sustain_real_pct
        assert a.median_terminal == pytest.approx(b.median_terminal, rel=1e-12)


# --------------------------------------------------------------------------- #
#  El desfase está en los defaults                                             #
# --------------------------------------------------------------------------- #


class TestElDesfaseEsElEstadoPorDefecto:

    def test_los_dos_defaults_no_coinciden(self):
        """Lo que vuelve grave a la fila: no hay que configurar nada mal para
        caer en el defecto. Si algún día coinciden, este test avisa que el
        argumento de la fila cambió."""
        assert WITHDRAWAL.default_longevity_years > MONTE_CARLO.default_horizon_years, (
            "los defaults dejaron de estar desfasados — el defecto ya no aparece "
            "sin configurar nada, y la fila hay que releerla"
        )

    def test_con_los_defaults_la_respuesta_cubre_la_longevidad_pedida(self):
        r = _run(
            horizon=MONTE_CARLO.default_horizon_years,
            longevity=WITHDRAWAL.default_longevity_years,
        )
        assert r.longevity_years == WITHDRAWAL.default_longevity_years
        mas_corto = _run(
            horizon=MONTE_CARLO.default_horizon_years,
            longevity=MONTE_CARLO.default_horizon_years,
        )
        assert r.prob_sustain_real_pct < mas_corto.prob_sustain_real_pct


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
