"""AUDIT-AIIO-3 — las convicciones ilegibles se apartan; borrar la de un ticker que no está no escribe nada.

``get_convictions`` leía un archivo ilegible como ``{}`` y lo dejaba; ``remove_conviction`` hacía
``convs.pop(ticker, None)`` y **escribía igual** el resultado (``{}``): eliminar una posición —o guardar el
formulario— con un archivo truncado reemplazaba todas las convicciones declaradas por un objeto vacío. Además
el guardado era ``write_text`` directo (no atómico): un corte a mitad dejaba el archivo truncado, que es
justo lo que después se leía como vacío. Es el defecto de AUDIT-AIIO-1/2 (preferencias, historial de salud).

Regla: un archivo ilegible (no es JSON, no es un objeto, no es UTF-8) se mueve a
``personal_book_convictions.corrupt-<fecha>.json`` con sus bytes intactos y se lee como vacío; si no se puede
mover, ``set_all`` y ``remove_conviction`` lanzan ``ConvictionsUnavailable`` y no escriben encima; borrar una
convicción que no existe no toca el archivo; el guardado es atómico (temporal + reemplazo). Rutas en tmp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import data.personal_book_convictions as pbc
from data.personal_book_convictions import (
    ConvictionsUnavailable,
    get_convictions,
    remove_conviction,
    set_all,
)

TRUNCATED = b'{"GOOGL": "HIGH", "INTU": "MEDI'


@pytest.fixture
def path(tmp_path, monkeypatch) -> Path:
    p = tmp_path / "personal_book_convictions.json"
    monkeypatch.setattr(pbc, "_CONV_PATH", p)
    return p


def _asides(path: Path) -> list[Path]:
    return sorted(path.parent.glob("personal_book_convictions.corrupt-*.json"))


@pytest.mark.parametrize("content", [
    TRUNCATED,
    b'["GOOGL", "INTU"]',                 # JSON, but not an object
    b"\xff\xfe\x00 not utf-8",
])
def test_an_unreadable_file_is_set_aside_with_its_bytes_intact(path, content):
    path.write_bytes(content)
    assert get_convictions() == {}
    [aside] = _asides(path)
    assert aside.read_bytes() == content
    assert not path.exists()


def test_removing_a_conviction_that_is_not_there_writes_nothing(path):
    """Deleting a position runs this for every ticker, convinced or not: it must not rewrite the file."""
    path.write_bytes(TRUNCATED)
    assert remove_conviction("ZZZZ") == {}
    [aside] = _asides(path)
    assert aside.read_bytes() == TRUNCATED               # before the fix: the file was rewritten as «{}»
    assert not path.exists()                             # nothing to remove, nothing written


def test_removing_a_ticker_that_has_no_conviction_leaves_a_good_file_byte_identical(path, monkeypatch):
    set_all({"GOOGL": "HIGH", "INTU": "LOW"})
    before = path.read_bytes()

    def no_write(_convictions):
        raise AssertionError("remove_conviction wrote the file although there was nothing to remove")

    monkeypatch.setattr(pbc, "_save", no_write)      # same bytes would hide a rewrite: forbid the call itself
    assert remove_conviction("ZZZZ") == {"GOOGL": "HIGH", "INTU": "LOW"}
    assert path.read_bytes() == before


def test_removing_a_conviction_that_exists_removes_only_that_one(path):
    set_all({"GOOGL": "HIGH", "INTU": "LOW"})
    assert remove_conviction("googl") == {"INTU": "LOW"}
    assert json.loads(path.read_text(encoding="utf-8")) == {"INTU": "LOW"}


def test_saving_the_form_over_an_unreadable_file_keeps_the_old_bytes(path):
    path.write_bytes(TRUNCATED)
    assert set_all({"GOOGL": "HIGH"}) == {"GOOGL": "HIGH"}
    assert json.loads(path.read_text(encoding="utf-8")) == {"GOOGL": "HIGH"}
    [aside] = _asides(path)
    assert aside.read_bytes() == TRUNCATED               # before the fix: gone after this save


def test_when_the_file_cannot_be_moved_nothing_is_written_over_it(path, monkeypatch):
    path.write_bytes(TRUNCATED)

    def refuse(self, target):
        raise OSError("disco de solo lectura")

    monkeypatch.setattr(Path, "replace", refuse)
    assert get_convictions() == {}
    with pytest.raises(ConvictionsUnavailable):
        set_all({"GOOGL": "HIGH"})
    with pytest.raises(ConvictionsUnavailable):
        remove_conviction("GOOGL")
    assert path.read_bytes() == TRUNCATED


def test_a_failed_save_leaves_the_previous_file_whole(path, monkeypatch):
    """Not atomic before: ``write_text`` truncated the file first, so a cut mid-write produced the very
    unreadable file this PR is about."""
    set_all({"GOOGL": "HIGH"})
    before = path.read_bytes()
    real_replace = Path.replace

    def fail_on_final_swap(self, target):
        if Path(target) == path:
            raise OSError("sin espacio")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_on_final_swap)
    with pytest.raises(OSError):
        set_all({"GOOGL": "LOW", "KO": "MEDIUM"})
    assert path.read_bytes() == before                   # the old file, whole
    assert get_convictions() == {"GOOGL": "HIGH"}
    assert list(path.parent.glob("*.tmp")) == []         # and no temporary left holding the convictions


def test_a_good_file_with_one_bad_level_is_read_as_before_and_untouched(path):
    path.write_text(json.dumps({"GOOGL": "HIGH", "KO": "SUPER"}), encoding="utf-8")
    before = path.read_bytes()
    assert get_convictions() == {"GOOGL": "HIGH"}        # the bad level is ignored, as always
    assert path.read_bytes() == before
    assert _asides(path) == []


def test_a_missing_or_empty_file_is_just_empty(path):
    assert get_convictions() == {}
    path.write_bytes(b"  \n")
    assert get_convictions() == {}
    assert _asides(path) == []


def test_an_invalid_level_is_still_refused_by_the_form_save(path):
    with pytest.raises(ValueError):
        set_all({"GOOGL": "SUPER"})
    assert not path.exists()


# --- la página: «guardadas» sólo si se guardaron -------------------------------------------------------

@pytest.fixture
def book(tmp_path, monkeypatch):
    import pandas as pd

    import portfolio.tracker as tracker_mod
    from portfolio.tracker import Portfolio, Position

    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {"currentPrice": 100.0, "sector": "Technology"})
    monkeypatch.setattr(tracker_mod, "get_history", lambda *a, **k: pd.DataFrame())
    p = Portfolio(file_path=tmp_path / "portfolio.json")
    p.positions["AAPL"] = Position("AAPL", 10, 90.0, "2024-01-15", sector="Technology")
    return p


def _page(book):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard/views/3_Portfolio.py"), default_timeout=60)
    at.session_state["portfolio"] = book
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def test_the_form_says_saved_when_it_saved_and_leaves_the_old_copy_aside(path, book):
    path.write_bytes(TRUNCATED)
    at = _page(book)                                       # rendering the form reads the file: it is set aside
    next(b for b in at.button if "Guardar convicciones" in b.label).click().run()
    assert any("Convicciones guardadas" in s.value for s in at.success)
    assert json.loads(path.read_text(encoding="utf-8")) == {"AAPL": "MEDIUM"}
    [aside] = _asides(path)
    assert aside.read_bytes() == TRUNCATED


def test_the_form_does_not_say_saved_when_the_file_could_not_be_written(path, book, monkeypatch):
    path.write_bytes(TRUNCATED)

    def refuse(self, target):
        raise OSError("disco de solo lectura")

    at = _page(book)
    path.write_bytes(TRUNCATED)                           # the render set it aside; put it back
    monkeypatch.setattr(Path, "replace", refuse)
    next(b for b in at.button if "Guardar convicciones" in b.label).click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert not any("Convicciones guardadas" in s.value for s in at.success)
    assert any("No se pudieron guardar las convicciones" in e.value for e in at.error)
    assert path.read_bytes() == TRUNCATED


def test_the_atomic_temporaries_are_ignored_by_git():
    import subprocess

    root = Path(__file__).resolve().parents[1]
    for name in ("data/personal_book_convictions.json.tmp", "data/user_preferences.json.tmp",
                 "data/plan_health_history.json.tmp"):
        assert subprocess.run(["git", "check-ignore", "-q", name], cwd=root).returncode == 0, name


def test_deleting_a_position_returns_a_warning_with_the_real_cause_when_the_conviction_cannot_be_cleaned(
    path, book, monkeypatch
):
    """The dialog confirm cannot be driven from AppTest (the dialog needs its own click's rerun), so the
    step it runs is a helper and is tested directly."""
    from dashboard.shared import delete_position_and_conviction

    set_all({"AAPL": "HIGH"})
    real = pbc.remove_conviction

    def disk_full(ticker):
        raise OSError("sin espacio en disco")

    monkeypatch.setattr(pbc, "remove_conviction", disk_full)
    warn = delete_position_and_conviction(book, "AAPL")
    assert "AAPL" not in book.positions                       # the position is gone either way
    assert warn is not None and "sin espacio en disco" in warn and "ilegible" not in warn
    monkeypatch.setattr(pbc, "remove_conviction", real)
    assert get_convictions() == {"AAPL": "HIGH"}               # nothing was touched


def test_deleting_a_position_with_an_unreadable_conviction_file_says_so_and_loses_nothing(path, book, monkeypatch):
    from dashboard.shared import delete_position_and_conviction

    path.write_bytes(TRUNCATED)

    def refuse(self, target):
        raise OSError("disco de solo lectura")

    monkeypatch.setattr(Path, "replace", refuse)
    warn = delete_position_and_conviction(book, "AAPL")
    assert warn is not None and "AAPL" in warn
    assert path.read_bytes() == TRUNCATED


def test_deleting_a_position_that_has_a_conviction_removes_both(path, book):
    from dashboard.shared import delete_position_and_conviction

    set_all({"AAPL": "HIGH", "KO": "LOW"})
    assert delete_position_and_conviction(book, "AAPL") is None
    assert "AAPL" not in book.positions
    assert get_convictions() == {"KO": "LOW"}
