"""Oráculo: el comité juzga a un cripto con criterios de cripto, no de empresa.

El defecto, medido contra la corrida de BTC del 2026-09-21 (Groq, `.context/btc/`):

1. **Escala.** El panel recibía ``Score del motor (determinista): 35.0/100``. La
   fórmula cripto (``base + técnico − vol − drawdown + moat``) no llega a 100 —
   su máximo teórico es ``CRYPTO_MOAT.max_achievable_score()`` — y para BTC menos
   todavía, porque su drawdown de −83 % es un máximo de toda la serie y penaliza
   siempre. El sufijo ``[cripto: adjusted_score]`` nombraba la FUENTE, no la
   escala. Textual del Abogado del Diablo: «El score determinista de 35/100 indica
   una valoración muy desfavorable comparada con otros activos tradicionales» —
   el agente comparando explícitamente contra la distribución de acciones.

2. **Datos.** Macro, PM y Coach recibían OCHO líneas, sin un solo dato nativo del
   activo: ni volatilidad, ni drawdown, ni escasez de suministro, ni ciclo de
   halving, ni market cap. Todo eso ya estaba calculado en ``fund.notes`` y sólo
   lo leía el Analista Fundamental.

3. **Mandatos.** Al Abogado del Diablo se le pedía buscar "apalancamiento,
   deterioro de márgenes, valuación exigente" sobre un activo sin estados
   contables, y devolvió "dependencia cíclica" y "riesgo de moat" — relleno, no
   escepticismo. El PM dimensionaba con "~8-15 %" mientras
   ``ProfileConfig.max_crypto_pct`` del perfil conservador dice 3 %.

La garantía que esto NO puede romper: los prompts de una acción quedan byte por
byte como estaban. El camino de equity funciona y no es lo que se está arreglando.

Sin red y sin LLM.
"""

from __future__ import annotations

import pytest

from analysis.committee_prompts import (
    behavioral_coach_prompt,
    committee_context_block,
    devils_advocate_prompt,
    macro_strategist_prompt,
    portfolio_manager_prompt,
)
from config import CRYPTO_COMMITTEE, CRYPTO_MOAT
from tests.test_prompts import _crypto_fund, _equity_fund, _tech

#: Vocabulario de estados contables. Nada de esto existe en un activo digital, y
#: pedírselo al panel produce relleno con forma de análisis.
EQUITY_VOCABULARY = (
    "ROE", "ROIC", "P/E", "D/E", "Margen neto", "Margen de seguridad",
    "apalancamiento", "deterioro de márgenes", "valuación exigente", "Piotroski",
)

CRYPTO_ROLE_PROMPTS = {
    "Estratega Macro": macro_strategist_prompt,
    "Abogado del Diablo": devils_advocate_prompt,
    "Portfolio Manager": portfolio_manager_prompt,
    "Behavioral Coach": behavioral_coach_prompt,
}


def _crypto_prompts() -> dict:
    fund, tech = _crypto_fund(), _tech("BTC-USD")
    return {role: fn(fund, tech) for role, fn in CRYPTO_ROLE_PROMPTS.items()}


def _equity_prompts() -> dict:
    fund, tech = _equity_fund(), _tech()
    return {role: fn(fund, tech) for role, fn in CRYPTO_ROLE_PROMPTS.items()}


class TestNingunAgenteMideUnCriptoConRatiosDeEmpresa:
    @pytest.mark.parametrize("role", sorted(CRYPTO_ROLE_PROMPTS))
    @pytest.mark.parametrize("term", EQUITY_VOCABULARY)
    def test_el_vocabulario_de_estados_contables_no_aparece(self, role, term):
        prompt = _crypto_prompts()[role]
        assert term not in prompt, (
            f"{role} recibe {term!r} sobre un activo sin estados financieros"
        )

    def test_anti_trampa_ese_vocabulario_sigue_vivo_para_una_accion(self):
        """El defecto no se arregla vaciando los prompts de todo el mundo."""
        equity = _equity_prompts()
        assert "ROE" in equity["Estratega Macro"], "una acción perdió sus ratios"
        assert "deterioro de márgenes" in equity["Abogado del Diablo"]


class TestLaEscalaDelScoreSeDeclara:
    def test_un_cripto_no_se_mide_sobre_100(self):
        block = committee_context_block(_crypto_fund(), _tech("BTC-USD"))
        assert "/100" not in block, "el score cripto sigue anunciándose en la escala de equity"

    def test_el_techo_declarado_es_el_de_la_formula_no_un_literal(self):
        """Derivado de config: si se recalibra la fórmula, la escala lo sigue."""
        block = committee_context_block(_crypto_fund(), _tech("BTC-USD"))
        assert f"/{CRYPTO_MOAT.max_achievable_score():.0f}" in block

    def test_se_prohibe_explicitamente_compararla_con_acciones(self):
        block = committee_context_block(_crypto_fund(), _tech("BTC-USD"))
        assert "NO la compares con el 0–100 de acciones" in block

    def test_una_accion_conserva_su_escala_sobre_100(self):
        block = committee_context_block(_equity_fund(), _tech())
        assert "Score del motor (determinista): 70.0/100" in block


class TestElPanelVeLosDatosNativosDelActivo:
    @pytest.mark.parametrize("role", sorted(CRYPTO_ROLE_PROMPTS))
    def test_volatilidad_y_drawdown_llegan_a_todas_las_voces(self, role):
        prompt = _crypto_prompts()[role]
        assert "Volatilidad anualizada" in prompt, f"{role} opina sin volatilidad"
        assert "Drawdown máximo histórico" in prompt, f"{role} opina sin drawdown"

    @pytest.mark.parametrize("role", sorted(CRYPTO_ROLE_PROMPTS))
    def test_el_ciclo_de_halving_y_el_tamano_llegan(self, role):
        prompt = _crypto_prompts()[role]
        assert "Ciclo halving" in prompt, f"{role} opina sin la fase del ciclo"
        assert "Market cap" in prompt, f"{role} opina sin el tamaño del activo"

    def test_una_nota_ausente_no_imprime_un_placeholder(self):
        """``_crypto_fund`` omite ``crypto_supply`` a propósito.

        Un ``N/D`` en el bloque duro sería exactamente el defecto del moat otra
        vez: un hueco con nombre de dato. La línea simplemente no se emite.
        """
        block = committee_context_block(_crypto_fund(), _tech("BTC-USD"))
        assert "Suministro emitido" not in block
        assert "N/D" not in block and "n/d" not in block.split("Sector/Industria")[1][:400]

    def test_las_claves_impresas_salen_de_config(self):
        assert "crypto_vol" in CRYPTO_COMMITTEE.context_note_keys
        assert "crypto_halving" in CRYPTO_COMMITTEE.context_note_keys


_POSTURA = {
    "profile_key": "aggressive", "profile_name": "Agresivo", "max_position_pct": 18.0,
    "max_crypto_pct": 10.0, "exigencia_pct": 70.0, "margin_pct": 5.0,
    "planning_scenario": "central",
}


class TestElPortfolioManagerDimensionaDentroDeLaPostura:
    """EO-5b: el techo es el del Perfil del inversor, no el de un Conservador fijo."""

    def test_cripto_cita_el_max_crypto_pct_de_la_postura_y_no_la_banda_de_equity(self):
        prompt = portfolio_manager_prompt(_crypto_fund(), _tech("BTC-USD"), None, _POSTURA)
        assert "10%" in prompt                       # el techo del Perfil Agresivo, a mano
        assert "Perfil Agresivo" in prompt
        assert "8-15%" not in prompt, "el PM sigue dimensionando con la banda de una acción"

    def test_cripto_sin_perfil_no_inventa_un_techo(self):
        prompt = portfolio_manager_prompt(_crypto_fund(), _tech("BTC-USD"))
        assert "no hay Postura" in prompt and "NO propongas un tamaño" in prompt
        assert "techo por ticker cripto" not in prompt

    def test_una_accion_cita_el_maximo_por_nombre_de_la_postura(self):
        prompt = portfolio_manager_prompt(_equity_fund(), _tech(), None, _POSTURA)
        assert "máximo 18% por nombre" in prompt
        assert "exigencia de 70%" in prompt and "margen de seguridad de 5%" in prompt
        assert "Escenario central" in prompt
        assert "~8-15%" not in prompt

    def test_el_techo_cambia_con_el_perfil_y_no_esta_en_el_texto(self):
        otro = {**_POSTURA, "max_crypto_pct": 3.0, "profile_name": "Conservador"}
        assert "3%" in portfolio_manager_prompt(_crypto_fund(), _tech("BTC-USD"), None, otro)
        assert "Perfil Conservador" in portfolio_manager_prompt(_equity_fund(), _tech(), None, otro)


class TestElCoachNombraTrampasDeCripto:
    def test_las_trampas_son_de_la_clase_de_activo(self):
        prompt = behavioral_coach_prompt(_crypto_fund(), _tech("BTC-USD"))
        assert "halving" in prompt
        assert "capitulación" in prompt

    def test_una_accion_no_las_recibe(self):
        assert "halving" not in behavioral_coach_prompt(_equity_fund(), _tech())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
