"""Oráculo PLAN-SESION-ACTIVO: Mi Plan y Portfolio no pueden hablar de planes distintos sin decirlo.

Mi Plan muestra «📍 Plan actual (esta sesión)» con la corrida del Optimizer
(`st.session_state["optimizer_result"]`); Portfolio, las alertas y el comité
miden contra el plan **activo** (`prefs.active_plan_id` → `plan_store`). Guardar
no activaba, así que tras optimizar con perfil Agresivo Portfolio seguía
comparando contra «Ejemplo · Conservador 30 años» (cargado antes desde la
portada) y pedía rebalancear con una deriva del 100 %, sin avisar nada.

Contra `main` (`5dd1440`) fallan: los helpers no existen, Mi Plan no avisa
«Borrador sin activar» y guardar no cambia `active_plan_id`.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from data.plan_context import (
    is_sample_plan,
    load_sample_plan,
    sample_plan_ids,
    session_plan_is_unsaved_target,
    session_weights,
)
from tests.test_plan_page_runtime import PAGE, _all_text, _FakePrefs, _snap, stores  # noqa: F401
from tests.test_plan_save_params_oracle import _opt

SAMPLE_ID = "ejemplo-conservador-30y"


# --------------------------------------------------------------------------- #
#  Helpers puros                                                              #
# --------------------------------------------------------------------------- #

def test_sample_ids_come_from_inside_the_files_not_the_stems():
    ids = sample_plan_ids()
    assert SAMPLE_ID in ids                    # el archivo es conservador_30y.json
    assert "conservador_30y" not in ids


def test_a_sample_plan_is_recognised_and_a_user_plan_is_not():
    assert is_sample_plan(load_sample_plan("conservador_30y"))
    assert not is_sample_plan(_snap())
    assert not is_sample_plan(None)


def test_session_run_against_a_different_active_plan_is_flagged():
    sample = load_sample_plan("conservador_30y")
    assert session_plan_is_unsaved_target(_opt(), sample)      # AAPL 100 vs BRK-B/JNJ/…


def test_session_run_without_active_plan_is_flagged():
    assert session_plan_is_unsaved_target(_opt(), None)


def test_no_session_run_means_nothing_to_compare():
    assert not session_plan_is_unsaved_target(None, load_sample_plan("conservador_30y"))


def test_a_saved_and_activated_session_compares_equal():
    """Mismo redondeo que `from_session` (2 decimales): guardar la sesión y
    activarla apaga el aviso."""
    opt = _opt()
    snap = _snap()
    snap.allocation = [{"symbol": s, "weight_pct": w} for s, w in session_weights(opt).items()]
    assert not session_plan_is_unsaved_target(opt, snap)


# --------------------------------------------------------------------------- #
#  La página                                                                  #
# --------------------------------------------------------------------------- #

def _open(prefs) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["optimizer_result"] = _opt()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def test_mi_plan_says_the_session_is_a_draft_and_names_the_active_plan(stores):  # noqa: F811
    stores.plans.upsert(load_sample_plan("conservador_30y"))
    text = _all_text(_open(_FakePrefs(active_plan_id=SAMPLE_ID)))
    assert "Borrador sin activar" in text
    assert "Ejemplo · Conservador 30 años" in text


def test_saving_over_a_sample_active_plan_activates_the_new_one(stores):  # noqa: F811
    stores.plans.upsert(load_sample_plan("conservador_30y"))
    prefs = _FakePrefs(active_plan_id=SAMPLE_ID)
    at = _open(prefs)
    assert at.checkbox(key="plan_save_activate").value is True   # el activo es un ejemplo
    at.button(key="plan_save_btn").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert prefs.active_plan_id not in ("", SAMPLE_ID)
    assert "Borrador sin activar" not in _all_text(at)


def test_saving_over_an_own_active_plan_does_not_steal_it_by_default(stores):  # noqa: F811
    stores.plans.upsert(_snap())
    prefs = _FakePrefs(active_plan_id="retiro-2045")
    at = _open(prefs)
    assert at.checkbox(key="plan_save_activate").value is False
    at.button(key="plan_save_btn").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert prefs.active_plan_id == "retiro-2045"
