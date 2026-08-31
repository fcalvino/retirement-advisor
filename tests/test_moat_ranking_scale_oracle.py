"""Oracle for U3-7b — el moat se rankea con la regla que no lo mide.

U3-7 arregló las **etiquetas**: dos escalas existen y no son intercambiables —
con la capa de IA el total corre 0–20 y sin ella es el tramo cuantitativo solo,
0–12, donde los umbrales de 14/8/4 vuelven «Wide» *inalcanzable por
construcción*. Por eso ``classify_moat`` exige ``ai_available`` en cada call
site en vez de asumirlo.

Esta fila es el mismo supuesto de escala única, en los **pesos**. El Optimizer
normaliza el moat por ``/20`` en los dos lugares donde ordena.

## La fila describe un defecto y hay otro

Dice: *«una fila sin IA queda sistemáticamente peor rankeada por no haber sido
enriquecida, no por la empresa»*. Eso necesita una población **mixta** — filas
con IA compitiendo contra filas sin ella.

Medido sobre las 150 equities cacheadas: el ``moat_score`` va de 0,5 a 12,0 y
**ninguna supera 12**. Ninguna pasó por la capa de IA, así que la población es
**uniforme** y no hay penalización relativa entre enriquecidas y no
enriquecidas. Lo que sí hay es una miscalibración:

    con moat ≤ 12 dividido por 20, el término de moat pesa el 60 % de lo que
    dice ``cfg.moat_weight``

Las dos cosas son ciertas y el arreglo cubre las dos: escalar por el techo que
efectivamente aplica a esa fila. Si algún día se corre el screener con IA, la
población se vuelve mixta y aparece el defecto que la fila describe.

## La prueba más limpia está en un comentario del propio código

``_core_rank`` documenta ``moat_factor = (moat / 20.0) + 0.5  # range 0.5–1.5``.
El rango real, con moat ≤ 12, es **0,53–1,10**. Con ``/12`` da 0,54–1,50 —
exactamente lo que el comentario promete. El código entrega el 60 % de su propia
intención declarada.

Efecto medido sobre el down-select: cambian 1 de 20 candidatos en Conservador,
2 de 30 en Moderado y 2 de 45 en Agresivo.

Sin red, sin Streamlit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import MOAT, OPTIMIZER_PROFILES
from portfolio.optimizer import PortfolioOptimizer

ROOT = Path(__file__).resolve().parents[1]


def _t(symbol="X", *, score=70.0, div=2.0, moat=6.0, ai=False):
    return {
        "symbol": symbol, "adjusted_score": score, "dividend_yield": div,
        "moat_score": moat, "moat_ai_available": ai, "tailwind_score": 0.0,
        "sector": "Technology",
    }


# --------------------------------------------------------------------------- #
#  El techo del moat depende de si la IA corrió                                #
# --------------------------------------------------------------------------- #


class TestElTechoLoDecideLaCapaQueCorrio:

    def test_existe_una_sola_funcion_que_resuelve_el_techo(self):
        """Igual que ``classify_moat`` para las etiquetas: una sola, expuesta, y
        que exige saber si la IA corrió en vez de asumirlo."""
        from analysis.moat import moat_scale_max

        assert moat_scale_max(ai_available=True) == pytest.approx(
            MOAT.quant_max_score + MOAT.ai_max_score
        )
        assert moat_scale_max(ai_available=False) == pytest.approx(MOAT.quant_max_score)

    def test_los_dos_techos_son_los_que_el_motor_usa(self):
        """12 y 20 no son literales elegidos acá: son el tramo cuantitativo y el
        total con IA, y tienen que salir de config."""
        assert MOAT.quant_max_score == 12.0
        assert MOAT.ai_max_score == 8.0

    def test_un_score_normalizado_llega_a_uno_en_su_propia_escala(self):
        """La propiedad que hace comparable a las dos escalas: un moat perfecto
        vale 1,0 en cualquiera de las dos. Es lo que hoy no pasa — un 12 sobre
        20 vale 0,6, así que la mejor fila posible sin IA arranca perdiendo."""
        from analysis.moat import moat_scale_max

        assert 12.0 / moat_scale_max(ai_available=False) == pytest.approx(1.0)
        assert 20.0 / moat_scale_max(ai_available=True) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
#  Los dos sitios que ordenan                                                  #
# --------------------------------------------------------------------------- #


class TestElDownSelectUsaLaEscalaCorrecta:

    def test_un_moat_perfecto_sin_ia_pesa_como_un_moat_perfecto(self):
        """El defecto, aislado: hoy la mejor fila posible sin IA (12) aporta al
        ranking lo mismo que una de 12 sobre 20, o sea el 60 % de su valor."""
        opt = PortfolioOptimizer("moderate")
        cfg = opt.cfg

        perfecto_sin_ia = opt._rank_score(_t(moat=12.0, ai=False))
        sin_moat = opt._rank_score(_t(moat=0.0, ai=False))
        aporte = perfecto_sin_ia - sin_moat

        assert aporte == pytest.approx(cfg.moat_weight, rel=1e-9), (
            f"un moat perfecto sin IA aporta {aporte:.4f} cuando el peso "
            f"configurado es {cfg.moat_weight:.4f} — está entregando el "
            f"{aporte / cfg.moat_weight:.0%} de lo que config declara"
        )

    def test_un_moat_perfecto_con_ia_tambien(self):
        """Anti-cheat: el arreglo no es cambiar 20 por 12, es usar el techo que
        corresponde. Con IA el techo sigue siendo 20."""
        opt = PortfolioOptimizer("moderate")
        aporte = (
            opt._rank_score(_t(moat=20.0, ai=True)) - opt._rank_score(_t(moat=0.0, ai=True))
        )
        assert aporte == pytest.approx(opt.cfg.moat_weight, rel=1e-9)

    def test_una_fila_sin_ia_no_pierde_contra_una_con_ia_por_no_estar_enriquecida(self):
        """El defecto que la fila describe, y que hoy no se puede ver porque la
        población cacheada es toda sin IA. Con una mixta aparece: dos empresas
        igual de buenas en su propia escala tienen que rankear igual."""
        opt = PortfolioOptimizer("moderate")
        sin_ia = opt._rank_score(_t("A", moat=6.0, ai=False))     # la mitad de su techo
        con_ia = opt._rank_score(_t("B", moat=10.0, ai=True))     # la mitad del suyo
        assert sin_ia == pytest.approx(con_ia, rel=1e-9)


class TestElCoreRankUsaLaEscalaCorrecta:

    def test_el_factor_cubre_el_rango_que_su_comentario_promete(self):
        """La prueba más limpia del defecto, y sale del propio código.

        ``_core_rank`` documenta ``range 0.5–1.5``. Con moat ≤ 12 sobre 20 el
        rango real es 0,53–1,10: el código entrega el 60 % de su intención
        declarada. Con el techo correcto un moat perfecto llega a 1,5.
        """
        from portfolio.optimizer import moat_rank_factor

        assert moat_rank_factor(0.0, ai_available=False) == pytest.approx(0.5)
        assert moat_rank_factor(12.0, ai_available=False) == pytest.approx(1.5)
        assert moat_rank_factor(0.0, ai_available=True) == pytest.approx(0.5)
        assert moat_rank_factor(20.0, ai_available=True) == pytest.approx(1.5)

    def test_el_comentario_del_codigo_dejo_de_mentir(self):
        src = (ROOT / "portfolio" / "optimizer.py").read_text(encoding="utf-8")
        assert "/ 20.0) + 0.5" not in src, (
            "sigue el /20 hardcodeado en el factor de ranking del core"
        )


# --------------------------------------------------------------------------- #
#  La medición que motiva la fila, fijada                                      #
# --------------------------------------------------------------------------- #

#: Lo medido sobre las 150 equities cacheadas el 2026-08-30, embebido como dato
#: y no leído de un archivo temporal. Un test que depende del scratchpad de una
#: sesión se saltea para siempre en CI, y un skip permanente es un verde por
#: ausencia — la misma clase de defecto que este archivo existe para atrapar.
MOAT_OBSERVADO_MIN = 0.5
MOAT_OBSERVADO_MAX = 12.0
EQUITIES_MEDIDAS = 150


class TestLaPoblacionCacheadaEraUniforme:
    """Lo que corrige la premisa de la fila: no había penalización relativa
    porque no había filas con IA contra las cuales perder."""

    def test_el_maximo_observado_no_supero_el_techo_cuantitativo(self):
        assert MOAT_OBSERVADO_MAX <= MOAT.quant_max_score, (
            f"la medición dice que el máximo observado fue {MOAT_OBSERVADO_MAX} "
            f"sobre un techo cuantitativo de {MOAT.quant_max_score}: si el techo "
            f"cambió, la conclusión de que la población era uniforme hay que "
            f"rehacerla"
        )

    def test_con_esa_poblacion_el_defecto_es_de_escala_y_no_de_penalizacion(self):
        """Con todas las filas bajo el mismo techo, dividir por 20 no perjudica a
        ninguna *en particular*: encoge el término de moat entero.

        Es lo que la fila no dice, y cambia qué hay que arreglar — no es
        emparejar dos poblaciones, es usar la regla que mide.
        """
        from analysis.moat import moat_scale_max

        con_ia = moat_scale_max(ai_available=True)
        sin_ia = moat_scale_max(ai_available=False)
        assert MOAT_OBSERVADO_MAX / con_ia == pytest.approx(0.6), (
            "la miscalibración medida era del 60 % — si este número cambió, el "
            "argumento de la fila hay que rehacerlo"
        )
        assert MOAT_OBSERVADO_MAX / sin_ia == pytest.approx(1.0)


class TestElPesoDelMoatEsElQueConfigDeclara:

    @pytest.mark.parametrize("profile", sorted(OPTIMIZER_PROFILES))
    def test_en_los_tres_perfiles(self, profile):
        """El defecto real de hoy: con población uniforme sin IA, dividir por 20
        no penaliza a nadie en particular — encoge el término de moat entero al
        60 % frente al score y al dividendo."""
        opt = PortfolioOptimizer(profile)
        aporte = (
            opt._rank_score(_t(moat=MOAT.quant_max_score, ai=False))
            - opt._rank_score(_t(moat=0.0, ai=False))
        )
        assert aporte == pytest.approx(opt.cfg.moat_weight, rel=1e-9)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
