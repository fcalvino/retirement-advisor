"""Oracle for U6-1 — el proxy del optimizer deja de fingir puntos porcentuales.

La fila decía que el proxy *"no está anclado a nada"* y lo llamaba **inventado**.
Medido sobre las 149 equities cacheadas con ≥5 años de historia semanal, eso es
medio cierto y la mitad falsa, y la mitad falsa importa:

  * **No está inventado.** El ``adjusted_score`` sí predice el CAGR realizado:
    pendiente +20,8 pp por 100 puntos, p < 0,0001, y —esto es lo que valida el
    diseño— **intercepto medido de −1,43 %**, o sea el cero que el motor asume.
  * **Pero no está anclado.** La correlación entre el μ del optimizer y el drift
    del Monte Carlo —el único retorno observable que el motor calcula— es
    **+0,025**. Dos números que el producto muestra en la misma pantalla, los
    dos llamados alguna forma de "retorno", sin relación entre sí.
  * **Y no tiene la precisión que su formato promete.** R² = 0,116, y el rango
    p10–p90 de μ es de **3,4 pp** contra los 19 pp que abarca el CAGR real. Un
    número así no sostiene un "7,2 % anual" en pantalla.

**Por qué no se recalibra la constante.** La pendiente de 20,8 sale de regresar
el score de *hoy* contra el retorno de los *últimos diez años*: es hindsight, en
una ventana con 13 % de CAGR medio. Además no serviría — llevar el span de 0,18
a 0,417 mete **95 de 150 tickers** contra ``er_absolute_cap`` y el desvío de μ
queda en 1,41 pp contra los 1,45 actuales: la vista se **aplana**. El cap manda,
no el span.

Así que U6-1 se cierra por el lado de la etiqueta, no del número: μ sigue igual
—Black-Litterman lo necesita en unidades de retorno— y deja de **presentarse**
como una tasa anual. La transformación a índice es estrictamente monótona, así
que **ningún ordenamiento cambia**: es exactamente la misma decisión de cartera,
descrita sin prometer una precisión que no existe.

Sin red, sin Streamlit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from config import OPTIMIZER
from data.product_ux import (
    PROXY_INDEX_HELP,
    PROXY_INDEX_LABEL,
    PROXY_INDEX_SHORT,
    proxy_attractiveness_index,
)

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


#: Toda superficie que renderiza copy que una persona lee.
USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    "reports/investment_plan.py",
    "analysis/prompts.py",
    "analysis/committee_prompts.py",
    "data/product_ux.py",
]

#: `expected_return_pct` interpolado y seguido de un signo de porcentaje, con o
#: sin espacio. Es la forma exacta que este PR elimina de las pantallas.
#: `[^}\n]*` es lo que impide cruzar otra llave: sin eso el barrido tomaba el
#: `%` de la volatilidad tres interpolaciones más adelante y marcaba como
#: infractora una línea ya corregida.
_PROXY_AS_PCT_RE = re.compile(
    r"expected_return(?:_pct)?[^}\n]*\}\s*%|"          # f"{...expected_return_pct:.1f}%"
    r"expected_return(?:_pct)?[^}\n]*\}\s*anual",      # ...} anual
)


def _offenders(paths: list[str]) -> list[str]:
    return [
        f"{rel}:{n}: {line.strip()}"
        for rel in paths
        for n, line in enumerate(_src(rel).splitlines(), start=1)
        if _PROXY_AS_PCT_RE.search(line)
    ]


# --------------------------------------------------------------------------- #
#  El índice existe y no pierde información                                    #
# --------------------------------------------------------------------------- #


class TestElIndiceEsUnReordenamientoNoUnaPerdida:
    """Lo único que este PR no puede hacer es cambiar una decisión de cartera."""

    def test_es_estrictamente_monotono(self):
        """La garantía central: si μ(A) > μ(B), el índice de A > el de B.

        Sin esto el cambio de etiqueta sería un cambio de recomendación
        disfrazado, que es exactamente lo que la fila advierte con «blast radius
        sobre toda la asignación».
        """
        mus = [0.0, 0.5, 1.0, 2.5, 4.0, 5.35, 6.97, 8.73, 11.0, 13.99]
        idx = [proxy_attractiveness_index(m) for m in mus]
        assert idx == sorted(idx)
        assert all(b > a for a, b in zip(idx, idx[1:])), idx

    def test_preserva_el_orden_del_universo_medido(self):
        """Sobre el rango real que μ ocupa (p10 5,35 % – p90 8,73 %), el orden
        que ve el usuario tiene que ser el mismo que el que usa el optimizer."""
        mus = [5.35, 5.9, 6.4, 6.97, 7.5, 8.1, 8.73]
        idx = [proxy_attractiveness_index(m) for m in mus]
        assert [i for _, i in sorted(zip(mus, idx))] == sorted(idx)

    def test_el_tope_del_indice_es_el_cap_del_motor(self):
        """El 100 del índice es `er_absolute_cap`, no un número redondo elegido
        aparte: el cap ya es el techo real de μ."""
        cap_pct = OPTIMIZER.er_absolute_cap * 100
        assert proxy_attractiveness_index(cap_pct) == pytest.approx(100.0)
        assert proxy_attractiveness_index(cap_pct * 2) == pytest.approx(100.0)
        assert proxy_attractiveness_index(0.0) == pytest.approx(0.0)

    def test_no_devuelve_algo_que_se_lea_como_porcentaje(self):
        """Un índice que cae en 0–14 se leería como «14 %» igual. El reescalado
        a 0–100 es lo que lo saca del rango donde se confunde con μ."""
        assert proxy_attractiveness_index(6.97) > 14.0

    def test_tolera_lo_que_el_motor_puede_no_tener(self):
        assert proxy_attractiveness_index(None) is None
        assert proxy_attractiveness_index(-1.0) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
#  La etiqueta no promete una tasa                                             #
# --------------------------------------------------------------------------- #


class TestLaEtiquetaNoPrometeUnaTasaAnual:

    def test_el_rotulo_no_dice_retorno_ni_anual(self):
        for texto in (PROXY_INDEX_LABEL, PROXY_INDEX_SHORT):
            bajo = texto.lower()
            assert "%" not in texto, texto
            assert "anual" not in bajo, texto
            assert "retorno" not in bajo, texto

    def test_el_help_dice_que_solo_sirve_para_comparar(self):
        bajo = PROXY_INDEX_HELP.lower()
        assert "ordena" in bajo or "compar" in bajo, PROXY_INDEX_HELP
        assert "no es" in bajo, PROXY_INDEX_HELP

    def test_el_help_no_sigue_prometiendo_el_moat(self):
        """U5-6 sacó el término de moat de μ hace dos semanas y el help seguía
        diciendo «score + dividendo + moat». Una etiqueta que enumera un término
        que ya no existe es la misma clase de defecto que esta fila cierra."""
        assert "moat" not in PROXY_INDEX_HELP.lower(), PROXY_INDEX_HELP


# --------------------------------------------------------------------------- #
#  El barrido: ninguna pantalla lo imprime como tasa                           #
# --------------------------------------------------------------------------- #


class TestNingunaSuperficieLoImprimeComoTasa:

    def test_ninguna_pantalla_interpola_el_proxy_con_un_porcentaje(self):
        malos = _offenders(USER_FACING)
        assert not malos, (
            "el proxy sigue renderizándose como una tasa anual — es la forma "
            "exacta que U6-1 elimina:\n  " + "\n  ".join(malos)
        )

    def test_el_barrido_detecta_la_forma_que_dice_detectar(self):
        """Guarda sobre la guarda: un regex que no matchea nada da un verde
        vacío, que es peor que un rojo."""
        assert _PROXY_AS_PCT_RE.search('f"{result.expected_return_pct:.1f}%"')
        assert _PROXY_AS_PCT_RE.search('f"~{result.expected_return_pct:.1f}% anual"')
        assert _PROXY_AS_PCT_RE.search('"expected_return": f"{er:.1f}%"'.replace("er", "expected_return_pct"))
        # y no marca lo que no es
        assert not _PROXY_AS_PCT_RE.search('volatility_pct = f"{vol:.1f}%"')
        assert not _PROXY_AS_PCT_RE.search('result.expected_return_pct = round(x, 2)')


# --------------------------------------------------------------------------- #
#  La medición que cierra la fila, fijada                                      #
# --------------------------------------------------------------------------- #


class TestLaMedicionQueJustificaNoRecalibrar:
    """La fila decía «la constante 0.18, que nadie calibró contra nada». Ahora
    está medida, y lo que la medición dice es que recalibrarla no sirve. Estos
    tests fijan ese razonamiento contra el código, no contra un comentario."""

    def test_con_el_span_calibrado_el_score_mediano_ya_choca_contra_el_cap(self):
        """El argumento contra recalibrar, en una sola afirmación verificable.

        Con el span llevado a la pendiente medida (0,417), el score a partir del
        cual μ satura ``er_absolute_cap`` cae **por debajo del score medio del
        universo** (69,5 sobre las 149 equities cacheadas). O sea: más de la
        mitad de los candidatos quedaría pegada al mismo techo, indistinguible
        entre sí. Recalibrar sin subir el cap no afila la vista, la **aplana** —
        medido sobre el universo real, 95 de 150 tickers contra el cap y el
        desvío de μ pasando de 1,45 pp a 1,41 pp.

        Si algún día se sube el cap, este test falla y obliga a rehacer el
        razonamiento en vez de dejarlo escrito en un comentario que envejece.
        """
        from config import VIEW_WEIGHTS as V

        SCORE_MEDIO_DEL_UNIVERSO = 69.5      # 149 equities cacheadas, 2026-08-29
        span_calibrado = 0.2083 / V.score

        # score al que μ satura, con dividendo 0 (el caso más favorable al span)
        score_de_saturacion = (
            OPTIMIZER.er_absolute_cap / (V.score * span_calibrado) * 100
        )
        assert score_de_saturacion < SCORE_MEDIO_DEL_UNIVERSO, (
            f"con span {span_calibrado:.3f} el cap satura recién en score "
            f"{score_de_saturacion:.1f}, por encima del medio del universo "
            f"({SCORE_MEDIO_DEL_UNIVERSO}) — el argumento para no recalibrar "
            f"hay que rehacerlo"
        )

    def test_con_el_span_actual_el_cap_casi_no_muerde(self):
        """La contracara, que es la que hace del cap un guard y no una perilla:
        con el 0,18 vigente el cap sólo alcanza a un ticker del universo, así que
        hoy no está comprimiendo nada."""
        from config import VIEW_WEIGHTS as V

        score_de_saturacion = (
            OPTIMIZER.er_absolute_cap / (V.score * OPTIMIZER.score_return_span) * 100
        )
        assert score_de_saturacion > 100, (
            f"el cap satura en score {score_de_saturacion:.1f}: ya está mordiendo "
            f"dentro del rango de scores posible, y el proxy está más comprimido "
            f"de lo que este PR asume"
        )

    def test_el_intercepto_cero_del_motor_es_el_que_se_midio(self):
        """Lo único del diseño que la medición validó: μ = 0 cuando score = 0.
        El intercepto medido fue −1,43 %, indistinguible de cero al lado de una
        dispersión de 19 pp. Se fija para que un futuro refactor no le meta un
        término constante «para que no dé cero»."""
        from portfolio.optimizer import PortfolioOptimizer

        opt = PortfolioOptimizer("moderate")
        (mu_cero,) = opt._expected_returns(
            [{"symbol": "Z", "adjusted_score": 0.0, "dividend_yield": 0.0,
              "moat_score": 0.0, "tailwind_score": 0.0}]
        )
        assert mu_cero == pytest.approx(0.0, abs=1e-12)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
