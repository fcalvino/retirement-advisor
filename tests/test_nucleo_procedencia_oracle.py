"""Oracle for NUCLEO-PROCEDENCIA — el rótulo dice quién eligió el núcleo.

«🤖 Cartera núcleo (IA)» se decidía con ``bool(core_holdings_ai)``. Pero
``generate_optimizer_advice`` rellena ``core_holdings`` con el núcleo
determinístico cuando hay más de 45 posiciones, la API falla o el LLM devuelve el
núcleo vacío, así que la pantalla decía «IA» sin que el modelo hubiera elegido
nada. Y lo que el modelo sí devolvía no se contrastaba con la cartera: un símbolo
que el optimizador nunca asignó llegaba a la tabla, a la lista de compra y al plan
guardado.

El oráculo es la definición, no el código:

* la procedencia es ``ia`` solo si el modelo respondió **y** quedó al menos un
  símbolo de la cartera; cualquier otro camino es ``reglas_respaldo``;
* un símbolo es válido si está en ``result.tickers`` (sin importar mayúsculas ni
  espacios) — los 15 del prompt son un recorte del prompt, no de la cartera;
* los pesos del núcleo suman 100 (así los normaliza el núcleo determinístico);
* el ``why`` determinístico trae las tres cifras del ranking, y el ranking no se
  movió.

Sin red: el LLM se stubbea en ``_call_api``; el guard de red falla el test que se
escape.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from analysis.ai_analyzer import AIAnalyzer
from config import AI_PROVIDER_KEY_ENV, CORE_SOURCE, MOAT, AIConfig
from data.plan_store import PlanSnapshot, PlanStore
from portfolio.optimizer import (
    OptimizationResult,
    PortfolioOptimizer,
    TickerAllocation,
    moat_rank_factor,
)


def _clear_ai_env(monkeypatch) -> None:
    for var in set(AI_PROVIDER_KEY_ENV.values()) | {"AI_API_KEY"}:
        monkeypatch.delenv(var, raising=False)


def _analyzer(monkeypatch) -> AIAnalyzer:
    _clear_ai_env(monkeypatch)
    return AIAnalyzer(AIConfig(provider="claude", model="m", enabled=True, api_key="k"))


def _t(symbol: str, weight: float) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol, weight_pct=weight, adjusted_score=80.0, moat_score=9.0,
        dividend_yield_pct=1.0, expected_return_pct=8.0, volatility_pct=18.0,
        sector="Technology", is_ars=False, tailwind_score=0.0,
        tailwind_classification="Neutral",
    )


def _opt(n: int = 2) -> SimpleNamespace:
    """Cartera de ``n`` posiciones: AAPL, KO, T02, T03, …"""
    names = ["AAPL", "KO"] + [f"T{i:02d}" for i in range(2, n)]
    return SimpleNamespace(
        tickers=[_t(s, 100.0 / n) for s in names],
        sector_weights={"Technology": 100.0},
        profile_core_holdings=[{"symbol": "AAPL", "suggested_weight_pct": 100.0, "why": "reglas"}],
        profile_name="Moderado",
        expected_return_pct=8.0, volatility_pct=18.0, sharpe_ratio=0.4,
        dividend_yield_pct=1.0, moat_score_avg=9.0,
        rebalance_rationale="", warnings=[],
    )


def _llm(core: list[dict]):
    payload = json.dumps({
        "narrative": "n", "recommended_max_human_positions": 5,
        "core_holdings": core, "dropped_tickers": [], "human_review_tips": [],
    })
    return lambda self, prompt, max_tokens=None: payload


def _advice(monkeypatch, core: list[dict], opt=None) -> dict:
    with patch.object(AIAnalyzer, "_call_api", _llm(core)):
        return _analyzer(monkeypatch).generate_optimizer_advice(opt or _opt())


def _boom(self, prompt, max_tokens=None):
    raise RuntimeError("sin red")


def _symbols(core: list[dict]) -> list[str]:
    return [c["symbol"] for c in core]


# --------------------------------------------------------------------------- #
#  Procedencia: solo el éxito es «IA»                                          #
# --------------------------------------------------------------------------- #

class TestProcedenciaDelNucleo:

    def test_el_exito_es_ia(self, monkeypatch):
        out = _advice(monkeypatch, [
            {"symbol": "AAPL", "suggested_weight_pct": 60.0, "why": "moat"},
            {"symbol": "KO", "suggested_weight_pct": 40.0, "why": "yield"},
        ])
        assert out["core_source"] == CORE_SOURCE.IA
        assert _symbols(out["core_holdings"]) == ["AAPL", "KO"]
        assert out["core_notes"] == []

    def test_mas_de_45_posiciones_es_respaldo_y_no_llama_al_modelo(self, monkeypatch):
        called = []
        opt = _opt(46)
        with patch.object(AIAnalyzer, "_call_api", lambda *a, **k: called.append(1)):
            out = _analyzer(monkeypatch).generate_optimizer_advice(opt)
        assert called == []
        assert out["core_source"] == CORE_SOURCE.RESPALDO
        assert out["core_holdings"] == opt.profile_core_holdings

    def test_error_de_api_es_respaldo(self, monkeypatch):
        opt = _opt()
        with patch.object(AIAnalyzer, "_call_api", _boom):
            out = _analyzer(monkeypatch).generate_optimizer_advice(opt)
        assert out["core_source"] == CORE_SOURCE.RESPALDO
        assert out["core_holdings"] == opt.profile_core_holdings

    def test_nucleo_vacio_del_modelo_es_respaldo(self, monkeypatch):
        opt = _opt()
        out = _advice(monkeypatch, [], opt)
        assert out["core_source"] == CORE_SOURCE.RESPALDO
        assert out["core_holdings"] == opt.profile_core_holdings

    def test_todo_ajeno_a_la_cartera_es_respaldo(self, monkeypatch):
        opt = _opt()
        out = _advice(monkeypatch, [
            {"symbol": "ZZZZ", "suggested_weight_pct": 100.0, "why": "inventado"},
        ], opt)
        assert out["core_source"] == CORE_SOURCE.RESPALDO
        assert out["core_holdings"] == opt.profile_core_holdings
        assert any("ZZZZ" in n for n in out["core_notes"])

    def test_el_resultado_sin_ia_es_reglas_por_defecto(self):
        assert OptimizationResult(profile_name="Moderado", method="slsqp").core_source == CORE_SOURCE.REGLAS


# --------------------------------------------------------------------------- #
#  Validación contra la cartera                                                #
# --------------------------------------------------------------------------- #

class TestValidacionContraLaCartera:

    def test_un_simbolo_ajeno_se_descarta_con_aviso(self, monkeypatch):
        out = _advice(monkeypatch, [
            {"symbol": "AAPL", "suggested_weight_pct": 60.0, "why": "moat"},
            {"symbol": "ZZZZ", "suggested_weight_pct": 40.0, "why": "inventado"},
        ])
        assert _symbols(out["core_holdings"]) == ["AAPL"]
        assert out["core_source"] == CORE_SOURCE.IA
        assert any("ZZZZ" in n for n in out["core_notes"])
        # Lo que queda suma 100: el 40 % del ajeno no desaparece de la tabla.
        assert sum(c["suggested_weight_pct"] for c in out["core_holdings"]) == pytest.approx(100.0, abs=0.1)

    def test_mayusculas_espacios_y_duplicados(self, monkeypatch):
        out = _advice(monkeypatch, [
            {"symbol": " aapl ", "suggested_weight_pct": 50.0, "why": "a"},
            {"symbol": "AAPL", "suggested_weight_pct": 10.0, "why": "dup"},
            {"symbol": "ko", "suggested_weight_pct": 40.0, "why": "b"},
        ])
        assert _symbols(out["core_holdings"]) == ["AAPL", "KO"]

    def test_un_simbolo_fuera_de_los_15_del_prompt_pero_en_la_cartera_es_valido(self, monkeypatch):
        opt = _opt(20)      # el prompt recorta a 15; la cartera tiene 20
        out = _advice(monkeypatch, [
            {"symbol": "AAPL", "suggested_weight_pct": 50.0, "why": "a"},
            {"symbol": "T19", "suggested_weight_pct": 50.0, "why": "chico"},
        ], opt)
        assert _symbols(out["core_holdings"]) == ["AAPL", "T19"]
        assert out["core_notes"] == []

    @pytest.mark.parametrize("basura", ["mucho", None, "", float("nan"), -5, 0])
    def test_un_peso_basura_descarta_el_simbolo_con_aviso_y_no_rompe(self, monkeypatch, basura):
        """Un símbolo sin peso utilizable sería una fila de USD 0 en la lista de compra."""
        out = _advice(monkeypatch, [
            {"symbol": "AAPL", "suggested_weight_pct": basura, "why": "a"},
            {"symbol": "KO", "suggested_weight_pct": 50.0, "why": "b"},
        ])
        assert _symbols(out["core_holdings"]) == ["KO"]
        assert out["core_source"] == CORE_SOURCE.IA
        assert any("AAPL" in n for n in out["core_notes"])
        assert out["core_holdings"][0]["suggested_weight_pct"] == pytest.approx(100.0, abs=0.1)

    def test_todos_los_pesos_basura_es_respaldo(self, monkeypatch):
        opt = _opt()
        out = _advice(monkeypatch, [
            {"symbol": "AAPL", "suggested_weight_pct": "mucho", "why": "a"},
            {"symbol": "KO", "suggested_weight_pct": None, "why": "b"},
        ], opt)
        assert out["core_source"] == CORE_SOURCE.RESPALDO
        assert out["core_holdings"] == opt.profile_core_holdings

    def test_pesos_que_no_suman_100_se_renormalizan_con_aviso(self, monkeypatch):
        out = _advice(monkeypatch, [
            {"symbol": "AAPL", "suggested_weight_pct": 30.0, "why": "a"},
            {"symbol": "KO", "suggested_weight_pct": 30.0, "why": "b"},
        ])
        pesos = [c["suggested_weight_pct"] for c in out["core_holdings"]]
        assert sum(pesos) == pytest.approx(100.0, abs=0.1)
        assert pesos[0] == pytest.approx(pesos[1])
        assert out["core_notes"], "renormalizar sin decirlo es cambiarle la respuesta al modelo"

    def test_pesos_dentro_de_la_tolerancia_no_se_tocan(self, monkeypatch):
        tol = CORE_SOURCE.weight_sum_tolerance_pct
        out = _advice(monkeypatch, [
            {"symbol": "AAPL", "suggested_weight_pct": 60.0, "why": "a"},
            {"symbol": "KO", "suggested_weight_pct": 40.0 - tol / 2, "why": "b"},
        ])
        assert [c["suggested_weight_pct"] for c in out["core_holdings"]] == [60.0, 40.0 - tol / 2]
        assert out["core_notes"] == []


# --------------------------------------------------------------------------- #
#  Rótulo único                                                                #
# --------------------------------------------------------------------------- #

class TestRotuloUnico:

    def test_cada_procedencia_tiene_su_rotulo(self):
        rotulos = {s: CORE_SOURCE.label(s) for s in (CORE_SOURCE.IA, CORE_SOURCE.REGLAS, CORE_SOURCE.RESPALDO)}
        assert len(set(rotulos.values())) == 3
        assert "IA" in rotulos[CORE_SOURCE.IA]
        assert "IA" not in rotulos[CORE_SOURCE.REGLAS]
        assert "respaldo" in rotulos[CORE_SOURCE.RESPALDO].lower()
        assert "IA)" not in rotulos[CORE_SOURCE.RESPALDO]

    def test_un_plan_viejo_con_ia_sin_procedencia_no_afirma_ia(self):
        rotulo = CORE_SOURCE.label("", legacy_from_ai=True)
        assert "no registrada" in rotulo
        assert CORE_SOURCE.label("", legacy_from_ai=False) == CORE_SOURCE.label(CORE_SOURCE.REGLAS)

    def test_una_procedencia_desconocida_degrada_a_reglas(self):
        assert CORE_SOURCE.label("inventada") == CORE_SOURCE.label(CORE_SOURCE.REGLAS)


# --------------------------------------------------------------------------- #
#  PlanSnapshot                                                                #
# --------------------------------------------------------------------------- #

def _snapshot_opt(**kw):
    base = dict(
        profile_name="Moderado",
        tickers=[_t("AAPL", 40.0), _t("KO", 60.0)],
        expected_return_pct=8.5, volatility_pct=12.0, sharpe_ratio=0.55,
        dividend_yield_pct=2.4, adjusted_score_avg=75.0, moat_score_avg=14.0,
        max_drawdown_estimate_pct=18.0, sector_weights={},
        profile_core_holdings=[{"symbol": "KO", "suggested_weight_pct": 100.0, "why": "r"}],
        core_holdings_ai=[], ai_narrative="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestProcedenciaEnElPlan:

    def test_el_plan_guarda_la_procedencia(self):
        opt = _snapshot_opt(
            core_holdings_ai=[{"symbol": "AAPL", "suggested_weight_pct": 100.0, "why": "m"}],
            core_source=CORE_SOURCE.IA,
        )
        snap = PlanSnapshot.from_session(name="x", opt_result=opt)
        assert snap.core_source == CORE_SOURCE.IA
        assert snap.core_from_ai is True

    def test_el_respaldo_no_es_core_from_ai(self):
        opt = _snapshot_opt(core_source=CORE_SOURCE.RESPALDO)
        snap = PlanSnapshot.from_session(name="x", opt_result=opt)
        assert snap.core_source == CORE_SOURCE.RESPALDO
        assert snap.core_from_ai is False
        assert snap.core_holdings[0]["symbol"] == "KO"

    def test_un_resultado_sin_el_atributo_se_lee_como_reglas(self):
        """``optimizer_prev_result`` de una sesión anterior al cambio no lo trae."""
        snap = PlanSnapshot.from_session(name="x", opt_result=_snapshot_opt())
        assert snap.core_source == CORE_SOURCE.REGLAS
        assert snap.core_from_ai is False

    def test_un_resultado_viejo_con_nucleo_ia_y_sin_procedencia_conserva_core_from_ai(self):
        opt = _snapshot_opt(core_holdings_ai=[{"symbol": "AAPL", "suggested_weight_pct": 100.0, "why": "m"}])
        snap = PlanSnapshot.from_session(name="x", opt_result=opt)
        assert snap.core_from_ai is True
        assert snap.core_source == ""

    def test_un_plan_guardado_antes_del_campo_sigue_cargando(self, tmp_path):
        store = PlanStore(tmp_path / "plans.json")
        snap = PlanSnapshot.from_session(name="viejo", opt_result=_snapshot_opt())
        legacy = snap.to_dict()
        legacy.pop("core_source")
        legacy["core_from_ai"] = True
        store._write_raw([legacy])
        loaded = store.get("viejo")
        assert loaded is not None
        assert loaded.core_source == ""
        assert loaded.core_from_ai is True


# --------------------------------------------------------------------------- #
#  El «why» determinístico                                                     #
# --------------------------------------------------------------------------- #

class TestWhyDelNucleoDeterministico:

    @staticmethod
    def _alloc(symbol, weight, score, moat):
        return TickerAllocation(
            symbol=symbol, weight_pct=weight, expected_return_pct=8.0,
            volatility_pct=12.0, dividend_yield_pct=2.5, adjusted_score=score,
            moat_score=moat, sector="Technology",
        )

    def test_el_why_trae_peso_score_y_factor_moat_antes_del_recorte_de_la_tabla(self):
        opt = PortfolioOptimizer("conservative")
        a = self._alloc("AAA", 12.5, 80.0, 9.0)
        core = opt._select_core_holdings([a])
        why = core[0]["why"]
        factor = moat_rank_factor(9.0, ai_available=False)
        assert "12.5%" in why[:140]
        assert "80" in why[:140]
        assert f"{factor:.2f}" in why[:140]

    def test_el_ranking_no_se_movio(self):
        """Oráculo independiente: peso × score/100 × factor, tomado de la definición."""
        opt = PortfolioOptimizer("moderate")
        allocs = [
            self._alloc(f"S{i:02d}", 3.0 + (i * 7) % 11, 50.0 + (i * 13) % 40, 1.0 + (i * 5) % 11)
            for i in range(30)
        ]
        esperado = sorted(
            allocs,
            key=lambda a: a.weight_pct * (a.adjusted_score / 100.0)
            * (a.moat_score / MOAT.quant_max_score + 0.5),
            reverse=True,
        )[: opt.cfg.target_max_human_positions]
        assert _symbols(opt._select_core_holdings(allocs)) == [a.symbol for a in esperado]


# --------------------------------------------------------------------------- #
#  Mi Plan, la página real (AppTest — no es prueba en vivo)                    #
# --------------------------------------------------------------------------- #
#  El aviso y el rótulo viajan por ``getattr(result, "core_notes_ai")`` hasta
#  ``st.warning``: el dict de ``generate_optimizer_advice`` no prueba que la
#  página los dibuje. Sin red y sin IA: el resultado de la sesión está armado.

from pathlib import Path  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.test_plan_page_runtime import _FakePrefs, stores  # noqa: E402, F401

_PLAN_PAGE = str(Path(__file__).resolve().parents[1] / "dashboard" / "views" / "12_Plan.py")


def _plan_texts(at) -> str:
    chunks = []
    for coll in (at.markdown, at.caption, at.warning, at.info):
        chunks += [getattr(e, "value", "") or "" for e in coll]
    return "\n".join(chunks)


def _plan_page(opt) -> AppTest:
    at = AppTest.from_file(_PLAN_PAGE, default_timeout=60)
    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["optimizer_result"] = opt
    return at.run()


def test_mi_plan_rotula_ia_y_muestra_el_aviso_del_simbolo_descartado(stores):  # noqa: F811
    opt = _snapshot_opt(
        core_source=CORE_SOURCE.IA,
        core_holdings_ai=[{"symbol": "AAPL", "suggested_weight_pct": 100.0, "why": "moat"}],
        core_notes_ai=["La IA sugirió ZZZZ, que no está(n) en la cartera optimizada."],
    )
    at = _plan_page(opt)
    assert not at.exception, [str(e) for e in at.exception]
    text = _plan_texts(at)
    assert f"{CORE_SOURCE.label(CORE_SOURCE.IA)}** — 1 posiciones para gestión activa" in text
    assert any("ZZZZ" in w.value for w in at.warning)


def test_mi_plan_rotula_el_respaldo_y_no_dice_ia(stores):  # noqa: F811
    opt = _snapshot_opt(core_source=CORE_SOURCE.RESPALDO)
    at = _plan_page(opt)
    assert not at.exception, [str(e) for e in at.exception]
    text = _plan_texts(at)
    assert CORE_SOURCE.label(CORE_SOURCE.RESPALDO) in text
    assert CORE_SOURCE.label(CORE_SOURCE.IA) not in text


def test_mi_plan_con_un_resultado_sin_el_atributo_no_afirma_ia(stores):  # noqa: F811
    """``optimizer_prev_result`` de una sesión anterior al cambio: sin ``core_source``."""
    opt = _snapshot_opt(
        core_holdings_ai=[{"symbol": "AAPL", "suggested_weight_pct": 100.0, "why": "moat"}],
    )
    at = _plan_page(opt)
    assert not at.exception, [str(e) for e in at.exception]
    text = _plan_texts(at)
    assert CORE_SOURCE.label("", legacy_from_ai=True) in text
