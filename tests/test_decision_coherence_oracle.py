"""Oráculo: la acción emitida, su motivo y su confianza tienen que decir lo mismo.

Tres piezas producen una recomendación de compra y cada una está testeada por
separado: la escalera de score (`tests/test_decision_thresholds.py`), la tabla de
`confidence_for` (`tests/test_confidence_deterministic_oracle.py`) y la
presentación del motivo (`tests/test_decision_reason.py`). Lo que no está testeado
es la **coherencia entre las tres** cuando la acción no salió de la escalera.

El camino rule-based no puede producir esa combinación: `decide()` deriva la acción
del score. El camino AI sí — `AIAnalyzer._parse_response` acepta cualquiera de las
cinco acciones válidas y `apply_safety_overlay` sólo re-aplica blocks duros y
políticas blandas. Nada compara la acción del LLM contra `STRATEGY.buy_score`.

El oráculo está escrito desde la definición del producto, no desde el motor: una
acción de compra afirma que el score alcanza su banda, y una confianza HIGH afirma
que la evidencia de *esa* acción es fuerte. Los umbrales se leen de `config.py`
(CONTEXT §5); acá no hay un solo número escrito a mano.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from analysis.ranking import attach_percentiles, build_shortlist
from analysis.strategy import (
    Decision,
    RetirementStrategy,
    apply_safety_overlay,
    confidence_for,
)
from config import STRATEGY as S
from data.product_ux import decision_explanation

# --------------------------------------------------------------------------- #
#  Oráculo                                                                    #
# --------------------------------------------------------------------------- #

#: Banda mínima que autoriza cada acción, derivada de la escalera de `STRATEGY`.
#: Es la definición del producto ("STRONG BUY ⇒ score ≥ strong_buy_score"), no una
#: copia del `if` del motor: se construye del diccionario de config, así que se
#: mueve con él.
def oracle_min_score_for(action: str) -> float:
    return {
        "STRONG BUY": S.strong_buy_score,
        "BUY": S.buy_score,
        "HOLD": S.hold_score,
        "REDUCE": S.reduce_score,
        "SELL": float("-inf"),
    }[action]


def oracle_action_is_defensible(action: str, score: float) -> bool:
    """¿El score alcanza para *afirmar* esta acción?

    Sólo se juzga hacia arriba: emitir HOLD sobre un score de STRONG BUY es
    prudencia (y el motor la explica con `decisive_reason`); emitir BUY sobre un
    score de SELL es una recomendación de compra sin sustento.
    """
    if action in ("AVOID", ""):
        return True
    return score >= oracle_min_score_for(action)


_CONF = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

BUY_ACTIONS = ("STRONG BUY", "BUY")


def oracle_high_confidence_is_defensible(action: str, score: float) -> bool:
    """HIGH sobre una acción de compra exige que el score la sostenga.

    La rama SELL de `confidence_for` emite HIGH a propósito ("alta certeza de que
    hay que salir"). Esa certeza es sobre *vender*: heredada por un BUY se lee como
    lo contrario de lo que la evidencia dice.
    """
    if action not in BUY_ACTIONS:
        return True
    return score >= oracle_min_score_for(action)


# --------------------------------------------------------------------------- #
#  Fixtures                                                                   #
# --------------------------------------------------------------------------- #

def _fund(
    score: float,
    *,
    is_crypto: bool = False,
    dq: dict | None = None,
    negative_equity: bool = False,
    mos: float | None = 25.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol="TEST",
        total_score=score,
        adjusted_score=score,
        is_crypto=is_crypto,
        debt_equity=0.5,
        pb_ratio=2.0,
        negative_equity=negative_equity,
        margin_of_safety_pct=mos,
        graham_value=100.0,
        is_value_stock=lambda: mos is not None and mos >= S.min_margin_of_safety_pct,
        roe=20.0,
        revenue_cagr_5y=10.0,
        fcf_yield=4.0,
        payout_ratio=40.0,
        warnings=[],
        data_quality=dq,
        tailwind_classification="Neutral",
        tailwind_detail=None,
    )


def _tech(signal: str = "BULLISH", *, above_sma200: bool | None = True) -> SimpleNamespace:
    return SimpleNamespace(
        signal=signal,
        above_sma200=above_sma200,
        price_vs_52w_low_pct=20.0,
        rsi_weekly=55.0,
        golden_cross=False,
        sma200_slope_pct=2.0,
        warnings=[],
    )


def _ai_decision(action: str, score: float, signal: str = "BULLISH") -> Decision:
    """Lo que `AIAnalyzer._parse_response` construye: acción del LLM, score del motor."""
    return Decision(
        symbol="TEST",
        action=action,
        ai_confidence="HIGH",
        fundamental_score=score,
        technical_signal=signal,
        has_margin_of_safety=True,
    )


#: Un score cómodamente por debajo de todo rung de compra: zona SELL.
SELL_ZONE = S.reduce_score - 10


# --------------------------------------------------------------------------- #
#  El oráculo se auto-verifica                                                #
# --------------------------------------------------------------------------- #

class TestOracle:
    def test_cada_accion_pide_su_banda(self):
        for action in ("STRONG BUY", "BUY", "HOLD", "REDUCE"):
            t = oracle_min_score_for(action)
            assert oracle_action_is_defensible(action, t) is True
            assert oracle_action_is_defensible(action, t - 0.1) is False

    def test_sell_no_pide_banda_y_avoid_tampoco(self):
        assert oracle_action_is_defensible("SELL", 0.0) is True
        assert oracle_action_is_defensible("AVOID", 0.0) is True

    def test_high_solo_se_juzga_en_las_acciones_de_compra(self):
        assert oracle_high_confidence_is_defensible("SELL", SELL_ZONE) is True
        assert oracle_high_confidence_is_defensible("BUY", SELL_ZONE) is False


# --------------------------------------------------------------------------- #
#  Defecto #1 — una acción de compra por debajo de su banda sobrevive          #
# --------------------------------------------------------------------------- #

class TestNingunaCompraPorDebajoDeSuBanda:
    """El camino AI no re-aplica la escalera, así que el LLM decide la banda.

    Ver `docs/issues/SIGNAL_REASON_CONFIDENCE_ISSUES.md` — SIGNAL-1.
    """

    @pytest.mark.parametrize("action", BUY_ACTIONS)
    def test_el_overlay_no_deja_una_compra_sin_banda(self, action):
        fund, tech = _fund(SELL_ZONE), _tech("BEARISH")
        out = apply_safety_overlay(_ai_decision(action, SELL_ZONE, "BEARISH"), fund, tech)
        assert oracle_action_is_defensible(out.action, SELL_ZONE), (
            f"score {SELL_ZONE} salió como {out.action!r}: por debajo de "
            f"{oracle_min_score_for(action)} el motor recomienda comprar sin sustento"
        )

    def test_strong_buy_del_llm_se_capa_a_la_banda_que_el_score_alcanza(self):
        score = S.buy_score + 1          # alcanza BUY, no STRONG BUY
        fund, tech = _fund(score), _tech("BULLISH")
        out = apply_safety_overlay(_ai_decision("STRONG BUY", score), fund, tech)
        assert out.action != "STRONG BUY"

    def test_bearish_no_puede_quedar_como_compra_en_el_camino_ai(self):
        """`decide()` veta BUY con técnico BEARISH (`strategy.py:382`)."""
        score = S.buy_score + 5
        out = apply_safety_overlay(_ai_decision("BUY", score, "BEARISH"), _fund(score), _tech("BEARISH"))
        assert out.action not in BUY_ACTIONS

    def test_el_motivo_no_puede_afirmar_zona_de_compra_sin_banda(self):
        """La celda «Motivo» del Screener sale de `decision_explanation`."""
        out = apply_safety_overlay(_ai_decision("BUY", SELL_ZONE, "BEARISH"), _fund(SELL_ZONE), _tech("BEARISH"))
        headline = decision_explanation(out)["full_headline"]
        assert "zona de compra" not in headline, (
            f"score {SELL_ZONE} con motivo {headline!r} — el motivo contradice el score"
        )

    def test_avoid_no_es_una_senal_de_compra(self):
        """El veredicto de un block no puede entrar al embudo por su emoji."""
        from analysis.ranking import _is_buy

        assert _is_buy("⛔ AVOID") is False
        assert _is_buy(Decision(symbol="X", action="AVOID").action) is False

    def test_una_compra_sin_banda_llega_al_shortlist(self):
        """Consecuencia aguas abajo. `ranking._is_buy` propaga fielmente lo que el
        motor emitió: el arreglo va en `analysis/strategy.py`, no acá."""
        out = apply_safety_overlay(_ai_decision("BUY", SELL_ZONE, "BEARISH"), _fund(SELL_ZONE), _tech("BEARISH"))
        rows = attach_percentiles([
            {"Ticker": "TEST", "Signal": out.action, "Adj. Score": SELL_ZONE,
             "Score bruto": SELL_ZONE, "_dq": {"level": "good"}},
            # Compañía del run para que el percentil relativo no sea el que excluye:
            # lo que se está probando es el paso «con señal de compra», no el corte
            # por percentil.
            *[
                {"Ticker": f"PEER{i}", "Signal": "HOLD", "Adj. Score": SELL_ZONE - 10 - i,
                 "Score bruto": SELL_ZONE - 10 - i, "_dq": {"level": "good"}}
                for i in range(3)
            ],
        ])
        assert build_shortlist(rows).n_selected == 0


# --------------------------------------------------------------------------- #
#  Defecto #3 — la confianza no mira la acción que acompaña                    #
# --------------------------------------------------------------------------- #

class TestConfianzaCoherenteConLaAccion:
    """`confidence_for` recibe `action` y no lo usa (`strategy.py:36-82`).

    Ver SIGNAL-3.
    """

    @pytest.mark.parametrize("action", BUY_ACTIONS)
    def test_high_de_la_banda_sell_no_se_hereda_en_una_compra(self, action):
        conf = confidence_for(
            action, SELL_ZONE, "BEARISH",
            blocked=False, downgraded=False, data_quality_level="", negative_equity=False,
        )
        assert oracle_high_confidence_is_defensible(action, SELL_ZONE) or conf != "HIGH", (
            f"{action} con score {SELL_ZONE} salió con confianza {conf!r}; ese HIGH es "
            "la certeza de la banda SELL («hay que salir»), leída como convicción de compra"
        )

    def test_la_accion_emitida_cambia_la_confianza(self):
        """Mismo score y misma señal, dos acciones opuestas: no pueden compartir label."""
        kw = dict(blocked=False, downgraded=False, data_quality_level="", negative_equity=False)
        assert confidence_for("SELL", SELL_ZONE, "BEARISH", **kw) != confidence_for(
            "BUY", SELL_ZONE, "BEARISH", **kw
        )

    def test_el_overlay_no_emite_high_sobre_una_compra_sin_banda(self):
        out = apply_safety_overlay(_ai_decision("BUY", SELL_ZONE, "BEARISH"), _fund(SELL_ZONE), _tech("BEARISH"))
        assert oracle_high_confidence_is_defensible(out.action, SELL_ZONE) or out.confidence != "HIGH"


# --------------------------------------------------------------------------- #
#  Monotonía — empeorar el input nunca mejora la recomendación                  #
# --------------------------------------------------------------------------- #

class TestMonotonia:
    """Sobre el camino rule-based, que es el que sí deriva la acción del score.

    La monotonía en el score ya está fijada en
    `tests/test_decision_thresholds.py::test_action_never_improves_as_the_score_falls`;
    acá se cubren los otros dos ejes.
    """

    _RANK = {"AVOID": -1, "SELL": 0, "REDUCE": 1, "HOLD": 2, "BUY": 3, "STRONG BUY": 4}

    def _decide(self, score, signal, dq):
        return RetirementStrategy().decide(_fund(score, dq=dq), _tech(signal))

    @pytest.mark.parametrize("score", [S.strong_buy_score + 5, S.buy_score + 1, S.hold_score + 1])
    def test_degradar_la_calidad_de_datos_no_mejora_nada(self, score):
        peor = None
        for level in ("good", "partial", "poor"):
            d = self._decide(score, "BULLISH", {"level": level, "missing_fields": ["roe"]})
            actual = (self._RANK[d.action], _CONF[d.confidence])
            if peor is not None:
                assert actual <= peor, (
                    f"score={score} dq={level}: {d.action}/{d.confidence} mejoró respecto "
                    f"del nivel anterior"
                )
            peor = actual

    @pytest.mark.parametrize("score", [S.strong_buy_score + 5, S.buy_score + 1, S.hold_score + 1])
    def test_empeorar_la_senal_tecnica_no_mejora_nada(self, score):
        peor = None
        for signal in ("BULLISH", "NEUTRAL", "BEARISH"):
            d = self._decide(score, signal, {"level": "good"})
            actual = (self._RANK[d.action], _CONF[d.confidence])
            if peor is not None:
                assert actual <= peor, (
                    f"score={score} signal={signal}: {d.action}/{d.confidence} mejoró"
                )
            peor = actual


# --------------------------------------------------------------------------- #
#  La señal técnica como entrada de la matriz                                  #
# --------------------------------------------------------------------------- #

class TestSenalTecnicaEnLaMatriz:
    def test_bearish_veta_la_compra_y_lo_explica(self):
        """El veto de `decide()` que ningún test fijaba: la banda BUY con BEARISH."""
        score = S.buy_score + 5
        d = RetirementStrategy().decide(_fund(score), _tech("BEARISH"))
        assert d.action not in BUY_ACTIONS
        assert d.decisive_reason, "una acción que no sigue del score tiene que decir por qué"

    @pytest.mark.parametrize("signal", ["bullish", "UNKNOWN", "", "BULL", None])
    def test_una_senal_que_el_motor_no_conoce_se_lee_conservadora(self, signal):
        """Un string inesperado no puede *mejorar* la acción ni la confianza.

        `decide()` compara contra literales (`tech in ("BULLISH", "NEUTRAL")`,
        `tech != "BEARISH"`), así que cualquier valor desconocido cae del lado no
        alcista — que es lo correcto — y el gate técnico lo captura vía
        `above_sma200`. Esto lo fija.
        """
        score = S.strong_buy_score + 5
        d = RetirementStrategy().decide(_fund(score), _tech(signal, above_sma200=None))
        assert d.action not in ("STRONG BUY",)
        assert d.confidence != "HIGH"
