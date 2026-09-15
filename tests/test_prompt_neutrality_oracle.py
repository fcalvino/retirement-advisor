"""Oráculo: los 9 prompts dejan de suplantar la identidad del modelo (PR 2, H1/H3).

Siete de los nueve prompts abrían con «**Eres Grok, construido por xAI**», y el
docstring del módulo lo declaraba doctrina: *«This ensures Grok receives
instructions in its own persona regardless of which provider (Claude, Grok,
GPT-4o) is actually executing the request»*. El transporte por defecto es
Anthropic, así que en producción el prompt le decía al modelo que era otro
modelo. El registro que la app realmente quiere —directo, escéptico, sin
corporativismo— nunca dependió de la marca: vive en las oraciones que siguen a
la apertura, y sobrevive intacto a la sustitución. Sólo se fue la identidad.

El segundo defecto es de contrato, y es el que cuesta tokens. Cinco redacciones
distintas de «devolvé JSON» convivían en el mismo archivo, y **cuatro** de ellas
además autorizaban prosa fuera del objeto:

    «Podés agregar un breve comentario adicional después del JSON si ayuda a
     expresar matices de tu análisis»

Los cinco caminos desembocan en el mismo parser (`analysis/utils.py`
`extract_json_object`), o sea que ese permiso existía únicamente porque el parser
tolera basura alrededor: una laxitud de prompt tapando una laxitud de parser, sin
que nadie mida cuál de las dos falla. Con `max_tokens` acotado, esa prosa es
exactamente lo que empuja al JSON a truncarse — y un JSON truncado no es un
matiz, es una llamada perdida.

Lo que este archivo fija son invariantes sobre el string renderizado, no casos:

1. **Ningún prompt nombra un proveedor.** Ni «Grok» ni «xAI», en ninguno de los
   nueve ni en los del comité, ni en el módulo que los define.
2. **El contrato de salida es uno solo** —el de `committee_prompts`— y ningún
   prompt JSON autoriza texto después del objeto.
3. **El rol sigue siendo un rol.** Anti-trampa: la limpieza no se pudo haber
   hecho borrando la apertura entera, ni vaciando el registro que la sigue.

Sin red y sin LLM: se renderizan los prompts y se miran los strings.
"""

from __future__ import annotations

import pytest

from analysis import committee_prompts as cp
from analysis.prompts import (
    ANALYST_ROLE,
    JSON_ONLY_CONTRACT,
    alert_explanation_prompt,
    crypto_decision_prompt,
    crypto_moat_prompt,
    equity_decision_prompt,
    equity_moat_prompt,
    long_term_plan_narrative_prompt,
    portfolio_optimizer_advice_prompt,
    sector_country_tailwind_prompt,
)
from tests.test_prompts import (
    _crypto_fund,
    _crypto_info,
    _crypto_metrics,
    _equity_fund,
    _moat_quant,
    _plan_prompt,
    _sample_holdings,
    _tech,
)

#: Marcas de proveedor que ningún prompt puede volver a nombrar.
VENDOR_MARKS = ("Grok", "xAI")

#: El permiso que PR 2 borra, literal.
POST_JSON_PERMISSION = "después del JSON"


def _equity_info() -> dict:
    return {
        "longName": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "country": "United States",
        "longBusinessSummary": "Apple Inc. diseña y vende smartphones.",
    }


def _tailwind_detail():
    """Un tailwind real del catálogo curado, no un doble."""
    from analysis.tailwind import TailwindAnalyzer

    return TailwindAnalyzer().analyze("YPF", sector="Energy", country="Argentina")


def _optimizer_prompt() -> str:
    return portfolio_optimizer_advice_prompt(
        profile_name="Conservador",
        holdings=_sample_holdings(18),
        expected_return_pct=9.2,
        volatility_pct=13.8,
        sharpe=0.72,
        dividend_yield_pct=3.8,
        moat_avg=9.1,
        num_positions=18,
        sector_weights={"Technology": 28.0, "Financials": 18.0},
        max_position_pct=8.0,
        min_positions=10,
        max_volatility_pct=12.0,
        min_dividend_yield_pct=3.5,
        max_crypto_pct=3.0,
    )


def _long_term_plan_prompt() -> str:
    return long_term_plan_narrative_prompt(
        profile_name="Moderado",
        tickers=["AAPL", "KO"],
        weights=[60.0, 40.0],
        expected_return=8.5,
        volatility=12.0,
        sharpe=0.55,
        dividend_yield=2.4,
        horizon_years=25,
        initial_value=200_000.0,
        annual_withdrawal=36_000.0,
        inflation_rate=3.0,
        median_terminal=900_000.0,
        p10_terminal=300_000.0,
        p90_terminal=2_000_000.0,
        prob_ruin=2.0,
        prob_target=70.0,
        target_value=1_000_000.0,
    )


def all_prompts() -> dict[str, str]:
    """Los 9 prompts públicos de `analysis/prompts.py`, renderizados."""
    return {
        "equity_moat": equity_moat_prompt(_moat_quant(), "AAPL", _equity_info()),
        "equity_decision": equity_decision_prompt(_equity_fund(), _tech()),
        "crypto_moat": crypto_moat_prompt("BTC-USD", _crypto_info(), _crypto_metrics()),
        "crypto_decision": crypto_decision_prompt(_crypto_fund(), _tech("BTC-USD")),
        "alert_explanation": alert_explanation_prompt(
            "score_drop", "AAPL",
            {"prev_score": "72", "current_score": "60", "signal": "HOLD"},
        ),
        "long_term_plan_narrative": _long_term_plan_prompt(),
        "portfolio_optimizer_advice": _optimizer_prompt(),
        "plan_level_narrative": _plan_prompt(),
        "sector_country_tailwind": sector_country_tailwind_prompt(
            _tailwind_detail(), "YPF", {"longName": "YPF SA", "country": "Argentina"}
        ),
    }


#: Los que declaran un contrato JSON. `long_term_plan_narrative` pide Markdown a
#: propósito (eso es H4, y lo resuelve un PR posterior de la serie).
JSON_PROMPTS = tuple(k for k in all_prompts() if k != "long_term_plan_narrative")

ALL_NAMES = tuple(all_prompts())


@pytest.fixture(scope="module")
def prompts() -> dict[str, str]:
    return all_prompts()


class TestNingunPromptNombraUnProveedor:
    @pytest.mark.parametrize("name", ALL_NAMES)
    @pytest.mark.parametrize("mark", VENDOR_MARKS)
    def test_the_rendered_prompt_names_no_vendor(self, prompts, name, mark):
        assert mark not in prompts[name]

    def test_the_committee_prompts_name_no_vendor_either(self):
        """H10: el renombre no se detiene en el archivo que lo originó."""
        from pathlib import Path

        src = Path(cp.__file__).read_text(encoding="utf-8")
        for mark in VENDOR_MARKS:
            assert mark not in src

    def test_the_module_no_longer_documents_the_old_convention(self):
        """El docstring declaraba la suplantación como doctrina; ya no."""
        from pathlib import Path

        import analysis.prompts as ap

        src = Path(ap.__file__).read_text(encoding="utf-8")
        for mark in VENDOR_MARKS:
            assert mark not in src


class TestElContratoDeSalidaEsUnoSolo:
    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_no_prompt_authorises_prose_after_the_json(self, prompts, name):
        assert POST_JSON_PERMISSION not in prompts[name]

    @pytest.mark.parametrize("name", JSON_PROMPTS)
    def test_every_json_prompt_uses_the_canonical_wording(self, prompts, name):
        assert JSON_ONLY_CONTRACT in prompts[name]

    def test_the_canonical_wording_is_the_committee_one(self):
        """La fuente de verdad es `committee_prompts`, no una copia paralela."""
        assert cp.AGENT_JSON_SCHEMA.startswith(JSON_ONLY_CONTRACT)

    def test_the_markdown_prompt_is_excluded_on_purpose(self, prompts):
        """Anti-trampa: no se unificó el contrato convirtiendo todo a JSON."""
        assert JSON_ONLY_CONTRACT not in prompts["long_term_plan_narrative"]
        assert "Nada de JSON" in prompts["long_term_plan_narrative"]


class TestElRolSigueSiendoUnRol:
    """Anti-trampa: borrar la marca no puede ser borrar el rol ni el registro."""

    #: Los 7 que abrían con la persona de marca. Los otros 2 nunca la tuvieron.
    HAD_PERSONA = (
        "equity_moat", "equity_decision", "crypto_moat", "crypto_decision",
        "alert_explanation", "portfolio_optimizer_advice",
        "sector_country_tailwind",
    )

    @pytest.mark.parametrize("name", HAD_PERSONA)
    def test_the_neutral_role_opens_the_prompt(self, prompts, name):
        assert prompts[name].lstrip().startswith(ANALYST_ROLE)

    def test_the_role_is_a_role_and_not_an_identity_claim(self):
        assert "analista" in ANALYST_ROLE
        assert len(ANALYST_ROLE.split()) <= 20

    #: El registro que la app quiere. Ninguno de estos adjetivos era de la marca,
    #: así que borrarla no puede haberse llevado ninguno por delante.
    REGISTER_MARKS = ("voz propia", "directo", "claridad", "honesto", "escepticismo")

    @pytest.mark.parametrize("name", HAD_PERSONA)
    def test_the_register_survived_the_substitution(self, prompts, name):
        """Lo que la app quiere del rol es independiente de la marca."""
        low = prompts[name].lower()
        assert "riguroso" in low, "se fue el rol, no sólo la marca"
        assert any(m in low for m in self.REGISTER_MARKS), "se fue el registro"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
