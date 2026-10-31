"""AUDIT-MOTOR-3: guardar o borrar un plan que no se pudo escribir no se anuncia como hecho.

Desde #283 el almacén de planes dejó de pisar un archivo ilegible, pero ``upsert`` quedó mudo:
devolvía ``None`` tanto si guardó como si no, y «Plan guardado» salía igual. Acá se fija que:

* ``upsert`` y ``delete`` dicen si escribieron (``True``/``False``),
* la pantalla de Mi Plan no anuncia «borrado» cuando el archivo no se escribió (ni desactiva el plan),
* ningún sitio de ``dashboard/`` descarta el resultado de ``plan_store.upsert``.

Los esperados salen del contrato (escribió / no escribió), no de leer lo que devuelve el motor.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from data.plan_store import PlanStore
from tests.test_plan_page_runtime import (  # noqa: F401  (fixture ``stores`` y ayudantes de la página)
    _all_text,
    _app,
    _FakePrefs,
    _snap,
    stores,
)

ROOT = Path(__file__).resolve().parents[1]


def _store_that_cannot_write(tmp_path: Path) -> PlanStore:
    """Un almacén cuyo directorio padre es un archivo: ``mkdir`` falla, como un disco sin permisos."""
    blocker = tmp_path / "blocker"
    blocker.write_text("no soy un directorio")
    return PlanStore(blocker / "plans.json")


def test_upsert_says_true_when_the_plan_reached_the_disk(tmp_path):
    store = PlanStore(tmp_path / "plans.json")
    assert store.upsert(_snap()) is True
    assert store.get("retiro-2045") is not None


def test_upsert_says_false_when_the_file_could_not_be_written(tmp_path):
    store = _store_that_cannot_write(tmp_path)
    assert store.upsert(_snap()) is False
    assert store.get("retiro-2045") is None


def test_upsert_says_false_when_the_existing_file_could_not_be_read(tmp_path, monkeypatch):
    store = PlanStore(tmp_path / "plans.json")
    assert store.upsert(_snap("uno", "Uno")) is True
    with monkeypatch.context() as m:
        m.setattr(store, "_read_items", lambda: None)   # lectura con OSError: el archivo se deja como está
        assert store.upsert(_snap("dos", "Dos")) is False
    assert [s.id for s in store.list()] == ["uno"]


def test_delete_says_false_when_the_file_could_not_be_written(tmp_path, monkeypatch):
    store = PlanStore(tmp_path / "plans.json")
    store.upsert(_snap())
    with monkeypatch.context() as m:
        m.setattr(store, "_write_raw", lambda items: False)
        assert store.delete("retiro-2045") is False
    assert store.get("retiro-2045") is not None


def test_the_sample_loader_raises_instead_of_returning_a_plan_that_was_not_saved(tmp_path, monkeypatch):
    from dashboard import shared
    from data import plan_store as ps_mod

    monkeypatch.setattr(ps_mod, "plan_store", _store_that_cannot_write(tmp_path))
    from data.plan_context import list_sample_plans

    key = list_sample_plans()[0]["key"]
    with pytest.raises(OSError):
        shared.load_sample_plan_into_store(key)


def test_deleting_a_plan_whose_file_cannot_be_written_says_so_and_keeps_the_plan(stores, monkeypatch):  # noqa: F811
    stores.plans.upsert(_snap())
    at = _app(_FakePrefs(active_plan_id="retiro-2045"))
    assert not at.exception, [str(e) for e in at.exception]

    with monkeypatch.context() as m:
        m.setattr(stores.plans, "_write_raw", lambda items: False)
        at.button(key="del_retiro-2045").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any("No se pudo borrar" in e.value for e in at.error), _all_text(at)
    assert not any("borrado" in t.value for t in at.toast)
    assert stores.plans.get("retiro-2045") is not None
    assert at.session_state["user_prefs"].active_plan_id == "retiro-2045"   # no se desactivó un plan que sigue ahí


def test_deleting_a_plan_that_is_already_gone_refreshes_instead_of_blaming_the_disk(stores):  # noqa: F811
    """Borrado desde otra pestaña: ``delete`` da False porque no hay nada que borrar, no porque no se pueda escribir."""
    stores.plans.upsert(_snap())
    at = _app(_FakePrefs())
    assert stores.plans.delete("retiro-2045") is True      # la otra pestaña
    at.button(key="del_retiro-2045").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert not at.error, _all_text(at)


def test_deleting_a_plan_still_works_when_the_file_is_writable(stores):  # noqa: F811
    stores.plans.upsert(_snap())
    at = _app(_FakePrefs())
    at.button(key="del_retiro-2045").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert not at.error
    assert stores.plans.get("retiro-2045") is None


# --------------------------------------------------------------------------- #
#  Barrido: nadie descarta el resultado de ``plan_store.upsert``              #
# --------------------------------------------------------------------------- #

# (archivo, razón). El resultado se descarta a propósito.
_KNOWN_DISCARD = {
    "data/plan_context.py": (
        "refresh_plan_against_market devuelve la comparación calculada, no el guardado; "
        "``upsert`` ya deja el error en el log y la cifra mostrada es la real. Pendiente: BACKLOG, "
        "AUDIT-RESIDUALES (AUDIT-MOTOR-3)."
    ),
}


def _bare_upserts(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr in {"upsert", "delete"}
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "plan_store"
    ]


def test_no_production_code_throws_away_whether_a_plan_was_saved():
    offenders = {}
    for sub in ("dashboard", "data"):
        for path in (ROOT / sub).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            lines = _bare_upserts(path)
            if lines and rel not in _KNOWN_DISCARD:
                offenders[rel] = lines
    assert not offenders, f"estos sitios descartan el resultado de plan_store.upsert/delete: {offenders}"


def test_every_known_discard_still_exists():
    for rel in _KNOWN_DISCARD:
        assert _bare_upserts(ROOT / rel), f"{rel} ya no descarta el resultado: sacalo de _KNOWN_DISCARD"
