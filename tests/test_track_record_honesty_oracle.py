"""Oracle for U7-3 — el titular afirma más de lo que la muestra sostiene.

El track record quedó limpio con U5-18b y U5-18d. Su lectura honesta es que **no
se puede concluir nada**, y las pantallas concluyen dos cosas.

Medido sobre la muestra real (n=11) el 2026-08-30:

    tasa de acierto   45,5 %   banda ±35,1 pp   → [10,4 , 80,5]   contiene el 50 %
    exceso medio      +3,21    banda ±6,86      → [−3,65 , +10,07] contiene el 0

El intervalo del acierto va de «pésimo» a «excelente». Eso no dice que el motor
pierda: dice que la muestra no permite saberlo, que es otra cosa. Ningún corte
alcanza — BUY 6, HOLD 5, ai 6, committee 5, MEDIUM 9, LOW 2, **HIGH 0** — contra
las ~50 por grupo que el docstring de ``mean_with_band`` pone como referencia.

## Tres defectos

**(1) La misma página sostiene dos estándares.** La tabla por acción muestra
«Margen ±» y una columna «Lectura» que dice *sin señal* cuando el intervalo cruza
el cero, porque ``hit_rate_by_action`` enriquece cada bloque con
``excess_band_pct`` e ``inconclusive``. Doce líneas más arriba, el titular afirma
«45 %» y «+3,2 %» en indicativo — porque ``summary_stats`` **no devuelve bandas**.
El arreglo va ahí, no en la página: un solo lugar, y las dos superficies
—la página y ``track_record_one_liner``— lo consumen.

La banda de la **tasa de acierto** no la calculaba nadie, y es la más ancha de
todas (±35 pp) y la que se muestra más grande.

**(2) El titular y el gráfico se contradicen en el signo.** El titular dice «le
ganó al mercado por +3,2 %» (media aritmética de excesos); el gráfico de equity
de la misma pantalla muestra el modelo en 0,9134 contra 1,0307 del benchmark —
perdiendo 8,7 mientras el mercado gana 3,1. **Los dos están bien calculados**:
uno promedia y el otro capitaliza, y con un desvío de 10,2 sobre un rango de
−23,5 a +13,7 el arrastre de volatilidad da vuelta la conclusión. El defecto es
presentarlos como si respondieran la misma pregunta — misma familia que
``median_cagr_pct`` (CONTEXT §8) y mismo remedio que U1-1/U1-2: vocabulario
canónico que los nombre distinto.

**(3) Una categoría sin una sola observación no puede calibrar.** El caption
invita a comparar HIGH contra LOW; HIGH tiene n=0 y LOW n=2. No saber no es
saber que no (U3-1, U5-14).

Sin red, sin Streamlit.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from analysis.track_record_scorer import (
    calibration_by_confidence,
    hit_rate_by_action,
    summary_stats,
)
from data.product_ux import EQUITY_CURVE_LABEL, EXCESS_MEAN_LABEL

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _row(hit: bool, excess: float, action="BUY", confidence="MEDIUM"):
    return {
        "action": action, "confidence": confidence, "source": "screener",
        "hit": hit, "excess_return_pct": excess, "benchmark_missing": False,
    }


#: La muestra real del 2026-08-30, con los excesos tal como están en la base —
#: no una aproximación. El primer intento de este fixture inventaba valores y su
#: docstring decía que reproducían la muestra: daban media −0,72 contra el +3,21
#: real. Un fixture que miente sobre lo que representa es la misma clase de
#: defecto que estos tests existen para atrapar.
#: n=11, 5 aciertos, media +3,2127, desvío 10,21.
MUESTRA_REAL = [
    _row(False, 11.31), _row(False, 13.72), _row(True, 4.4), _row(True, 1.39),
    _row(False, 9.48), _row(True, 4.07), _row(True, 8.59), _row(False, 8.59),
    _row(False, -23.52), _row(False, -3.32), _row(True, 0.63),
]


def test_el_fixture_reproduce_la_muestra_real():
    """Guarda sobre el fixture: si deja de reproducir la muestra medida, los
    números de todo este archivo dejan de significar lo que dicen."""
    import statistics

    ex = [r["excess_return_pct"] for r in MUESTRA_REAL]
    assert len(MUESTRA_REAL) == 11
    assert sum(1 for r in MUESTRA_REAL if r["hit"]) == 5
    assert sum(ex) / len(ex) == pytest.approx(3.2127, abs=1e-3)
    assert statistics.stdev(ex) == pytest.approx(10.21, abs=0.01)


def _banda_de_referencia(valores: list[float]) -> float:
    """Student's t al 95 %, escrita desde la definición.

    No se importa ``mean_with_band``: si el motor y la referencia comparten
    implementación, el test no valida nada (CONTEXT §5).
    """
    from scipy import stats

    n = len(valores)
    media = sum(valores) / n
    var = sum((v - media) ** 2 for v in valores) / (n - 1)
    return float(stats.t.ppf(0.975, n - 1)) * math.sqrt(var / n)


# --------------------------------------------------------------------------- #
#  (1) El titular tiene que traer su banda                                     #
# --------------------------------------------------------------------------- #


class TestSummaryStatsTraeSusBandas:

    def test_devuelve_banda_para_el_exceso(self):
        s = summary_stats(MUESTRA_REAL)
        assert "excess_band_pct" in s and s["excess_band_pct"] is not None
        assert "inconclusive" in s

    def test_devuelve_banda_para_la_tasa_de_acierto(self):
        """La que nadie calculaba, y es la más ancha de todas."""
        s = summary_stats(MUESTRA_REAL)
        assert "hit_rate_band" in s and s["hit_rate_band"] is not None
        assert "hit_rate_inconclusive" in s

    def test_la_banda_del_exceso_coincide_con_la_referencia(self):
        s = summary_stats(MUESTRA_REAL)
        esperada = _banda_de_referencia([r["excess_return_pct"] for r in MUESTRA_REAL])
        # `mean_with_band` publica con 4 decimales; se compara a esa precisión.
        assert s["excess_band_pct"] == pytest.approx(esperada, abs=5e-5)

    def test_la_banda_del_acierto_se_calcula_sobre_los_ceros_y_unos(self):
        """Una tasa de acierto es la media de una variable 0/1, así que su banda
        sale de los mismos datos — no de los excesos, que es otra magnitud."""
        s = summary_stats(MUESTRA_REAL)
        esperada = _banda_de_referencia([1.0 if r["hit"] else 0.0 for r in MUESTRA_REAL])
        assert s["hit_rate_band"] == pytest.approx(esperada, abs=5e-5)

    def test_sobre_la_muestra_real_las_dos_son_inconclusas(self):
        """El hecho que motiva la fila: con n=11 ninguna de las dos concluye.

        El intervalo del acierto tiene que contener el 50 % de una moneda, y el
        del exceso tiene que contener el cero.
        """
        s = summary_stats(MUESTRA_REAL)
        assert s["inconclusive"] is True, "el exceso dejó de contener el cero"

        lo = s["overall_hit_rate"] - s["hit_rate_band"]
        hi = s["overall_hit_rate"] + s["hit_rate_band"]
        assert lo <= 0.5 <= hi, (
            f"el intervalo del acierto [{lo:.3f}, {hi:.3f}] ya no contiene el 0,5 "
            f"de una moneda al aire"
        )
        assert s["hit_rate_inconclusive"] is True

    def test_una_muestra_grande_y_consistente_si_concluye(self):
        """Anti-cheat: el arreglo agrega una banda, no apaga la conclusión.

        Con muchas observaciones del mismo signo el intervalo se despega del
        cero y ``inconclusive`` tiene que dar False, o el flag sería decorativo.
        """
        grande = [_row(True, 5.0 + (i % 3) * 0.5) for i in range(80)]
        s = summary_stats(grande)
        assert s["inconclusive"] is False
        assert s["hit_rate_inconclusive"] is False

    def test_tolera_lo_que_el_motor_puede_no_tener(self):
        vacio = summary_stats([])
        assert vacio["overall_hit_rate"] is None
        assert vacio["hit_rate_band"] is None
        assert vacio["hit_rate_inconclusive"] is True

    def test_la_forma_es_la_que_ya_usa_la_tabla_de_abajo(self):
        """Una sola convención. ``hit_rate_by_action`` ya devolvía
        ``excess_band_pct``/``inconclusive``; el titular usa los mismos nombres
        para que nadie tenga que traducir entre dos formas."""
        por_accion = hit_rate_by_action(MUESTRA_REAL)["BUY"]
        s = summary_stats(MUESTRA_REAL)
        for clave in ("excess_band_pct", "inconclusive"):
            assert clave in por_accion and clave in s


# --------------------------------------------------------------------------- #
#  El barrido: ninguna pantalla afirma sin su banda                            #
# --------------------------------------------------------------------------- #

USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    "data/product_ux.py",
]

#: `overall_hit_rate` o `mean_excess_pct` interpolados y formateados como número.
_AFIRMA_RE = re.compile(r"(overall_hit_rate|mean_excess_pct)[^}\n]*\}")
#: Lo que vuelve honesta a esa línea: que la banda o el flag aparezcan cerca.
_MITIGA_RE = re.compile(r"band|inconclusive|sin señal|sin_senal", re.IGNORECASE)
#: UNA línea a cada lado, no seis. Con una ventana ancha el `help=` contiguo
#: —que legítimamente nombra la banda— tapaba al titular de al lado, y la
#: mutación «la página vuelve a afirmar el porcentaje sin banda» sobrevivía al
#: barrido. La guarda de una afirmación vive pegada a ella, no en el vecindario.
_CONTEXTO = 1


class TestNingunaPantallaAfirmaSinSuBanda:

    def test_barrido(self):
        malos = []
        for rel in USER_FACING:
            lineas = _src(rel).splitlines()
            for n, linea in enumerate(lineas):
                if not _AFIRMA_RE.search(linea):
                    continue
                ventana = "\n".join(lineas[max(0, n - _CONTEXTO): n + _CONTEXTO + 1])
                if not _MITIGA_RE.search(ventana):
                    malos.append(f"{rel}:{n + 1}: {linea.strip()}")
        assert not malos, (
            "una superficie afirma la tasa de acierto o el exceso sin su banda — "
            "con n=11 el intervalo del acierto va de 10 % a 80 %:\n  " + "\n  ".join(malos)
        )

    def test_el_barrido_detecta_la_forma_que_dice_detectar(self):
        """Guarda sobre la guarda: un regex que no matchea nada da un verde
        vacío, que es peor que un rojo."""
        assert _AFIRMA_RE.search("f\"{stats['overall_hit_rate'] * 100:.0f}%\"")
        assert _AFIRMA_RE.search("f\"{stats['mean_excess_pct']:+.1f}%\"")
        assert not _AFIRMA_RE.search("stats['overall_hit_rate'] is not None")
        assert _MITIGA_RE.search("if s['hit_rate_inconclusive']:")

    def test_el_barrido_atrapa_una_afirmacion_pelada_pegada_a_un_help_honesto(self):
        """El caso exacto que dejaba pasar una ventana ancha.

        Un `help=` contiguo nombra la banda legítimamente; si el barrido mira
        seis líneas alrededor, ese help tapa a la métrica de al lado y la
        afirmación pelada pasa. La guarda tiene que estar pegada.
        """
        malo = [
            'm3.metric(',
            '    "Tasa de acierto",',
            "    f\"{stats['overall_hit_rate'] * 100:.0f}%\",",
            '    help=(',
            "        f\"margen de ±{_hr_band * 100:.0f} puntos\"",
            '    ),',
        ]
        n_malo = 2
        ventana = "\n".join(malo[max(0, n_malo - _CONTEXTO): n_malo + _CONTEXTO + 1])
        assert _AFIRMA_RE.search(malo[n_malo])
        assert not _MITIGA_RE.search(ventana), (
            "la ventana sigue siendo tan ancha que el help de al lado tapa la "
            "afirmación pelada"
        )


# --------------------------------------------------------------------------- #
#  (2) Promediar y capitalizar no son la misma pregunta                        #
# --------------------------------------------------------------------------- #


class TestLasDosAgregacionesTienenNombresDistintos:
    """El titular decía «le ganó al mercado por +3,2 %» mientras el gráfico de
    la misma pantalla mostraba el modelo por debajo del benchmark. Los dos bien
    calculados; uno promedia, el otro capitaliza."""

    def test_los_rotulos_existen_y_no_se_confunden(self):
        assert EXCESS_MEAN_LABEL != EQUITY_CURVE_LABEL
        assert EXCESS_MEAN_LABEL and EQUITY_CURVE_LABEL

    def test_cada_uno_nombra_su_operacion(self):
        from data.product_ux import EQUITY_CURVE_HELP, EXCESS_MEAN_HELP

        assert "promedi" in EXCESS_MEAN_HELP.lower(), EXCESS_MEAN_HELP
        assert "capitaliz" in EQUITY_CURVE_HELP.lower() or "compone" in EQUITY_CURVE_HELP.lower()

    def test_alguno_de_los_dos_avisa_que_pueden_discrepar(self):
        """Lo que un lector necesita saber y ninguna de las dos decía: que con
        dispersión alta el promedio y el capitalizado pueden dar conclusiones de
        signo opuesto. Medido: +3,21 de media contra 0,913 de capital."""
        from data.product_ux import EQUITY_CURVE_HELP, EXCESS_MEAN_HELP

        juntos = (EXCESS_MEAN_HELP + " " + EQUITY_CURVE_HELP).lower()
        assert "signo" in juntos or "distinto" in juntos or "discrepa" in juntos, (
            "ninguno de los dos help avisa que pueden contradecirse"
        )


# --------------------------------------------------------------------------- #
#  (3) Una categoría sin observaciones no calibra                              #
# --------------------------------------------------------------------------- #


class TestUnaCategoriaVaciaLoDice:

    def test_high_sin_observaciones_no_trae_una_tasa(self):
        """No saber no es saber que no (U3-1, U5-14)."""
        calib = calibration_by_confidence(MUESTRA_REAL)   # todas MEDIUM
        assert calib["HIGH"]["n"] == 0
        assert calib["HIGH"]["hit_rate"] is None

    def test_el_caption_no_invita_a_comparar_lo_que_no_hay(self):
        """El caption decía «un modelo bien calibrado acierta más cuando dice
        HIGH que cuando dice LOW». Con HIGH n=0 y LOW n=2 esa comparación no se
        puede hacer, y el texto no lo advertía."""
        page = _src("dashboard/pages/13_Track_Record.py")
        bloque = page[page.index("Calibración por nivel de confianza"):][:1200].lower()
        assert "muestra" in bloque or "n=" in bloque or "sin señal" in bloque, (
            "la sección de calibración sigue sin decir que un nivel puede no "
            "tener observaciones"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
