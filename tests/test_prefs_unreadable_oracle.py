"""AUDIT-AIIO-1 — un archivo de preferencias ilegible se aparta, no se pisa.

``UserPreferences.load`` devolvía los valores por defecto ante cualquier error de lectura y dejaba el archivo
donde estaba; cualquier ``save()`` posterior (elegir un perfil, silenciar un ticker, activar un plan: las
páginas guardan a cada paso) lo reescribía entero con esos valores por defecto. Un JSON truncado (corte de luz,
disco lleno) borraba edad, capital, ahorro, perfil, tickers vigilados, alertas de precio y plan activo en el
siguiente click, sin copia. Es el defecto que ``PlanStore._set_aside_unreadable`` ya corrigió para los planes.

Regla: un archivo ilegible (no es JSON, no es un objeto, bytes que no son UTF-8) se mueve a
``<nombre>.corrupt-<fecha>.json`` con sus bytes intactos; la carga sigue como si el archivo no existiera (la
plantilla del repo, ``onboarded: false``). Un archivo vacío no tiene nada que conservar; uno que otra sesión dejó
válido entre la lectura y el apartado no se toca; si no se puede mover, queda donde está. Sin red, rutas en tmp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import data.preferences as prefs_mod
from data.json_files import set_aside_unreadable
from data.preferences import UserPreferences

TRUNCATED = b'{"age": 47, "monthly_savings": 1500, "watched_tickers": ["AAPL", "KO'


@pytest.fixture
def path(tmp_path, monkeypatch) -> Path:
    p = tmp_path / "user_preferences.json"
    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", p)
    monkeypatch.setattr(prefs_mod, "_PREFS_EXAMPLE_PATH", tmp_path / "no_example.json")
    return p


def _asides(path: Path) -> list[Path]:
    return sorted(path.parent.glob("user_preferences.corrupt-*.json"))


@pytest.mark.parametrize("content", [
    TRUNCATED,
    b"[1, 2, 3]",                       # JSON, but not an object
    b'"hola"',
    b"\xff\xfe\x00 not utf-8",
])
def test_an_unreadable_file_is_set_aside_with_its_bytes_intact(path, content):
    path.write_bytes(content)
    loaded = UserPreferences.load()
    assert loaded.onboarded is False                      # defaults: the wizard asks again
    [aside] = _asides(path)
    assert aside.read_bytes() == content
    assert not path.exists()                              # free for a clean file


def test_the_next_save_no_longer_destroys_what_was_there(path):
    path.write_bytes(TRUNCATED)
    prefs = UserPreferences.load()
    prefs.choose_profile("Moderado")
    prefs.save()
    assert json.loads(path.read_text(encoding="utf-8"))["default_profile"] == "Moderado"
    [aside] = _asides(path)
    assert aside.read_bytes() == TRUNCATED                # before the fix: gone after this save


def test_the_template_seeds_the_clean_start_when_the_file_was_set_aside(path, tmp_path, monkeypatch):
    example = tmp_path / "example.json"
    example.write_text(json.dumps({"age": 35, "onboarded": False}), encoding="utf-8")
    monkeypatch.setattr(prefs_mod, "_PREFS_EXAMPLE_PATH", example)
    path.write_bytes(TRUNCATED)
    assert UserPreferences.load().age == 35
    assert len(_asides(path)) == 1


def test_a_readable_file_is_untouched(path):
    path.write_text(json.dumps({"age": 47, "onboarded": True, "monthly_savings": 1500.0}), encoding="utf-8")
    before = path.read_bytes()
    loaded = UserPreferences.load()
    assert loaded.age == 47 and loaded.monthly_savings == 1500.0
    assert path.read_bytes() == before
    assert _asides(path) == []


def test_an_empty_file_has_nothing_to_keep(path):
    path.write_bytes(b"   \n")
    assert UserPreferences.load().onboarded is False
    assert _asides(path) == []


def test_a_failed_move_leaves_the_file_where_it_was(path, monkeypatch):
    path.write_bytes(TRUNCATED)

    def refuse(self, target):
        raise OSError("disco de solo lectura")

    monkeypatch.setattr(Path, "replace", refuse)
    assert UserPreferences.load().onboarded is False
    assert path.read_bytes() == TRUNCATED
    assert _asides(path) == []


def test_a_profile_of_the_wrong_type_neither_crashes_the_load_nor_costs_the_rest_of_the_file(path):
    """«default_profile» as a list made ``_from_raw`` raise (unhashable): defaults, file left, next save wiped it."""
    content = json.dumps({"onboarded": True, "default_profile": ["x"], "age": 50}).encode()
    path.write_bytes(content)
    prefs = UserPreferences.load()
    assert prefs.age == 50                       # the keys that make sense survive (and no crash)
    assert _asides(path) == []                   # ``_from_raw`` copes with it now: nothing to move


def test_a_second_corrupt_file_in_the_same_microsecond_does_not_overwrite_the_first_copy(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    import data.json_files as jf

    monkeypatch.setattr(jf, "utc_now", lambda: datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc))
    p = tmp_path / "x.json"
    p.write_bytes(b"first{")
    assert set_aside_unreadable(p, "x", _is_object) == "moved"
    p.write_bytes(b"second{")
    assert set_aside_unreadable(p, "x", _is_object) == "moved"
    assert sorted(a.read_bytes() for a in tmp_path.glob("x.corrupt-*.json")) == [b"first{", b"second{"]


def test_a_pathologically_nested_file_is_set_aside_and_load_does_not_raise(path):
    path.write_bytes(b"[" * 100_000)
    assert UserPreferences.load().onboarded is False
    assert len(_asides(path)) == 1


# --- el helper ---------------------------------------------------------------------------------------

def _is_object(data) -> bool:
    return isinstance(data, dict)


def test_helper_reports_gone_for_a_missing_or_empty_file(tmp_path):
    assert set_aside_unreadable(tmp_path / "nope.json", "x", _is_object) == "gone"
    empty = tmp_path / "empty.json"
    empty.write_bytes(b"")
    assert set_aside_unreadable(empty, "x", _is_object) == "gone"
    assert empty.exists()


def test_helper_does_not_move_a_file_another_session_left_valid(tmp_path):
    """The first read failed; by the time we look again somebody saved a good file."""
    p = tmp_path / "a.json"
    p.write_text('{"ok": true}', encoding="utf-8")
    assert set_aside_unreadable(p, "x", _is_object) == "valid"
    assert p.read_text(encoding="utf-8") == '{"ok": true}'
    assert list(tmp_path.glob("a.corrupt-*")) == []


def test_helper_names_the_copy_after_the_file_and_keeps_the_suffix(tmp_path):
    p = tmp_path / "convictions.json"
    p.write_bytes(b"{")
    assert set_aside_unreadable(p, "x", _is_object) == "moved"
    [aside] = tmp_path.glob("convictions.corrupt-*.json")
    assert aside.read_bytes() == b"{"
