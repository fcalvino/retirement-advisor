"""Oráculo: un moat que nadie midió no puede llegarle al comité como un hallazgo.

El defecto, medido contra una corrida real (BTC, Groq, 2026-09-21):

    Dictamen BTC: REDUCE · LOW · lean −0.66 · quórum 100 % · panel completo
    Portfolio Manager: «El score del motor es bajo (35/100) y **no hay moat**…»
    Abogado del Diablo: «**Ausencia de moat** y dependencia total de la percepción
                         de valor…»   ← esto salió publicado como disenso

Cuatro de los cinco agentes fundamentaron el voto en la ausencia de un moat que
nunca se calculó. La página del comité corre con la IA apagada
(``15_Comite.py``: ``cached_full_analysis(..., ai_enabled=False)``) y el moat
cripto es **100 % IA por diseño** (``CryptoMoatConfig``: "no quantitative
financial-statement layer"), así que ``CryptoMoatDetail`` se quedaba con sus ceros
y ``moat_classification`` con su default — el literal ``"None"``, que es también
el nombre del peor bucket medido. El prompt imprimía ``Moat: None`` y los agentes
votaron sobre eso. Corrido con la capa IA, ese mismo BTC da **Narrow 5.0/8**.

Son TRES caminos al mismo string, y por eso el arreglo va en el prompt y no en la
página: IA deshabilitada, IA que falla, y un 429 de Groq — ``call_ai_api`` no
tiene retry (``analysis/moat.py``) y ``crypto_analyzer`` degrada a
``classification="None"`` sin señal alguna.

Es la misma lección que ``fundamental.reported_metric`` ya dejó escrita: "el feed
omitió esto" y "el feed dice cero" no pueden colapsar al mismo valor cuando toda
banda aguas abajo lo lee como un hallazgo.

Asimetría deliberada: un equity SIEMPRE tiene moat medido (el tramo cuantitativo
corre antes de consultar a la IA), así que sus prompts no cambian ni un byte.

Sin red y sin LLM.
"""

from __future__ import annotations

import pytest

from analysis.committee_prompts import (
    behavioral_coach_prompt,
    devils_advocate_prompt,
    macro_strategist_prompt,
    portfolio_manager_prompt,
)
from analysis.crypto_analyzer import CryptoMoatDetail
from analysis.moat import reported_moat_label
from analysis.prompts import MOAT_NOT_MEASURED_LABEL, crypto_decision_prompt
from tests.test_prompts import _crypto_fund, _equity_fund, _tech

#: El string exacto que el defecto le mostraba al panel.
THE_DEFECT = "Moat: None"


def _panel_prompts(fund, tech) -> dict:
    """Los cinco prompts del comité por ticker, como los arma ``CommitteeAnalyzer``."""
    return {
        "Analista Fundamental": crypto_decision_prompt(fund, tech),
        "Estratega Macro": macro_strategist_prompt(fund, tech),
        "Abogado del Diablo": devils_advocate_prompt(fund, tech),
        "Portfolio Manager": portfolio_manager_prompt(fund, tech),
        "Behavioral Coach": behavioral_coach_prompt(fund, tech),
    }


def _measured_crypto():
    """Un cripto cuyo moat SÍ se midió (Narrow 5.0/8 — lo que da BTC de verdad)."""
    fund = _crypto_fund()
    fund.crypto_moat_detail = CryptoMoatDetail(
        network_adoption=1.0, monetary_scarcity=1.0, security_decentralization=1.5,
        institutional_regulatory=1.0, tech_resilience=0.5,
        ai_total=5.0, total=5.0, classification="Narrow", bonus=5.0,
        ai_available=True, ai_reasoning="red dominante, escasez verificable",
    )
    fund.moat_classification = "Narrow"
    return fund


class TestUnMoatNoMedidoNoLlegaComoHallazgo:
    @pytest.mark.parametrize("role", list(_panel_prompts(_crypto_fund(), _tech("BTC-USD"))))
    def test_ningun_agente_recibe_el_string_del_defecto(self, role):
        prompts = _panel_prompts(_crypto_fund(), _tech("BTC-USD"))
        assert THE_DEFECT not in prompts[role], (
            f"{role} sigue recibiendo {THE_DEFECT!r}: un moat no calculado presentado "
            f"con el nombre del peor bucket medido"
        )

    @pytest.mark.parametrize("role", list(_panel_prompts(_crypto_fund(), _tech("BTC-USD"))))
    def test_el_panel_entero_se_entera_de_que_no_se_midio(self, role):
        """No alcanza con borrar la línea: el agente tiene que saber que falta.

        El Analista Fundamental omitía el bloque entero, y el modelo rellenó el
        hueco afirmando «moat crypto amplio (wide)». Un silencio también se
        completa; por eso la ausencia se nombra.
        """
        prompts = _panel_prompts(_crypto_fund(), _tech("BTC-USD"))
        assert MOAT_NOT_MEASURED_LABEL in prompts[role], (
            f"{role} no recibe ninguna señal de que el moat no se midió"
        )

    @pytest.mark.parametrize("role", list(_panel_prompts(_crypto_fund(), _tech("BTC-USD"))))
    def test_se_le_prohibe_explicitamente_usarlo_como_argumento(self, role):
        prompts = _panel_prompts(_crypto_fund(), _tech("BTC-USD"))
        assert "NO lo interpretes como ausencia de moat" in prompts[role], (
            f"{role} podría volver a votar sobre la no-medición"
        )

    @pytest.mark.parametrize("role", list(_panel_prompts(_measured_crypto(), _tech("BTC-USD"))))
    def test_un_moat_medido_si_llega_con_su_clasificacion(self, role):
        """Anti-trampa: el defecto no se arregla silenciando el moat siempre."""
        prompts = _panel_prompts(_measured_crypto(), _tech("BTC-USD"))
        assert "Narrow" in prompts[role], f"{role} perdió el moat que SÍ se midió"
        assert MOAT_NOT_MEASURED_LABEL not in prompts[role], (
            f"{role} recibe «no medido» sobre un moat que se midió"
        )


class TestLaAsimetriaConEquity:
    def test_un_equity_conserva_su_moat_medido(self):
        """El tramo cuantitativo de equity corre siempre: nunca es "no medido"."""
        assert reported_moat_label(_equity_fund()) == "Wide"

    def test_los_prompts_de_equity_no_cambian(self):
        """La línea del equity es la de antes, byte por byte."""
        from analysis.committee_prompts import _moat_line

        assert _moat_line(_equity_fund()) == "Moat: Wide"


class TestElSeamQueSeparaLosDosCasos:
    def test_sin_capa_ia_el_label_es_none_no_el_bucket_None(self):
        fund = _crypto_fund()
        assert fund.moat_classification == "None", "precondición: el default es el literal"
        assert reported_moat_label(fund) is None, (
            "el string 'None' y la ausencia de medición tienen que ser distinguibles"
        )

    def test_con_capa_ia_el_label_es_la_clasificacion(self):
        assert reported_moat_label(_measured_crypto()) == "Narrow"

    def test_un_429_degrada_igual_que_la_ia_apagada(self):
        """``crypto_analyzer`` traga la excepción y deja ai_available=False.

        Es el camino que el flag de la página (PR 3) NO puede cubrir, y la razón
        por la que el arreglo vive en el prompt.
        """
        fund = _crypto_fund()
        fund.crypto_moat_detail = CryptoMoatDetail(
            ai_available=False, ai_reasoning="[AI error: 429 rate limit]",
        )
        assert reported_moat_label(fund) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
