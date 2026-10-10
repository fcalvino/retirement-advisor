"""Oráculo IDEA5-LOTES: el Portfolio guarda lotes y no cambia ningún número visible.

IDEA-5 (``docs/plans/IDEA5_GANANCIA_CAPITAL_AR.md`` §6, D7, D8 y D10) necesita cada
compra por separado: la ley toma el costo por PEPS (LIG arts. 149 y 65), y el
promedio que guardaba ``add_position`` pisaba la fecha y el costo de la compra
anterior. Las posiciones viejas pasan a un lote único rotulado «costo promedio
migrado». Los valores esperados son literales (la cartera del usuario al
2026-10-10, sin notas), no recalculados como lo hace el código.
"""

from __future__ import annotations

import json

import pytest

import portfolio.tracker as tracker_mod
from portfolio.tracker import Portfolio

OLD_FORMAT = {
    "GOOGL": {"symbol": "GOOGL", "shares": 23.0, "avg_cost": 177.22,
              "purchase_date": "2025-06-09", "sector": "Communication Services", "notes": ""},
    "INTU": {"symbol": "INTU", "shares": 10.0, "avg_cost": 329.28,
             "purchase_date": "2026-05-29", "sector": "Technology", "notes": ""},
    "ADBE": {"symbol": "ADBE", "shares": 12.0, "avg_cost": 273.95,
             "purchase_date": "2026-08-19", "sector": "Technology", "notes": "core"},
}
#: shares × avg_cost, hecho a mano.
COST_BASIS = {"GOOGL": 4076.06, "INTU": 3292.80, "ADBE": 3287.40}


@pytest.fixture
def old_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {"sector": "Technology", "currency": "USD"})
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(OLD_FORMAT, indent=2))
    return path


def _visible(p: Portfolio) -> dict:
    return {
        s: (pos.shares, round(pos.avg_cost, 6), round(pos.cost_basis, 2), pos.purchase_date,
            pos.sector, pos.notes)
        for s, pos in p.positions.items()
    }


EXPECTED = {
    s: (v["shares"], v["avg_cost"], COST_BASIS[s], v["purchase_date"], v["sector"], v["notes"])
    for s, v in OLD_FORMAT.items()
}


def test_an_old_file_loads_with_the_same_numbers(old_file):
    assert _visible(Portfolio(file_path=old_file)) == EXPECTED


def test_an_old_position_becomes_one_migrated_lot(old_file):
    [lot] = Portfolio(file_path=old_file).positions["GOOGL"].lots
    assert (lot.date, lot.shares, lot.price_usd) == ("2025-06-09", 23.0, 177.22)
    assert lot.label == "costo promedio migrado"
    assert (lot.market, lot.instrument) == ("broker del exterior", "acción")


def test_save_and_reload_loses_nothing(old_file):
    p = Portfolio(file_path=old_file)
    p._save()
    again = Portfolio(file_path=old_file)
    assert _visible(again) == EXPECTED
    assert [vars(lot) for lot in again.positions["ADBE"].lots] == [
        vars(lot) for lot in p.positions["ADBE"].lots
    ]


def test_the_first_new_format_write_backs_up_the_old_file(old_file):
    original = old_file.read_text()
    Portfolio(file_path=old_file)._save()
    backups = list(old_file.parent.glob("portfolio.json.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == original
    Portfolio(file_path=old_file)._save()          # the file is new-format now: no second backup
    assert len(list(old_file.parent.glob("portfolio.json.bak-*"))) == 1


def test_two_buys_are_two_lots_with_the_old_average(old_file):
    """10 @ 100 el 2026-01-05 y 30 @ 120 el 2026-03-02: el promedio de antes era
    (1000 + 3600) / 40 = 115, y la fecha la de la primera compra."""
    p = Portfolio(file_path=old_file)
    assert p.add_position("MSFT", 10, 100.0, "2026-01-05") is None
    assert p.add_position("MSFT", 30, 120.0, "2026-03-02") is None
    pos = Portfolio(file_path=old_file).positions["MSFT"]
    assert [(lot.date, lot.shares, lot.price_usd, lot.label) for lot in pos.lots] == [
        ("2026-01-05", 10, 100.0, ""), ("2026-03-02", 30, 120.0, ""),
    ]
    assert (pos.shares, pos.avg_cost, pos.cost_basis, pos.purchase_date) == (
        40, 115.0, 4600.0, "2026-01-05",
    )


def test_a_partial_reduction_takes_the_oldest_lots_first(old_file):
    """PEPS (LIG arts. 149 y 65): sacar 15 de 10 @ 100 + 30 @ 120 vacía el primer
    lote y deja 25 @ 120 del segundo."""
    p = Portfolio(file_path=old_file)
    p.add_position("MSFT", 10, 100.0, "2026-01-05")
    p.add_position("MSFT", 30, 120.0, "2026-03-02")
    p.remove_position("MSFT", 15)
    pos = Portfolio(file_path=old_file).positions["MSFT"]
    assert [(lot.date, lot.shares) for lot in pos.lots] == [("2026-03-02", 25)]
    assert (pos.shares, pos.avg_cost, pos.purchase_date) == (25, 120.0, "2026-03-02")


def test_removing_everything_closes_the_position(old_file):
    p = Portfolio(file_path=old_file)
    p.remove_position("GOOGL")
    assert "GOOGL" not in Portfolio(file_path=old_file).positions


def test_editing_a_single_lot_position_edits_that_lot(old_file):
    p = Portfolio(file_path=old_file)
    assert p.update_position("INTU", 12, 300.0, "2026-05-30", "nota") is True
    [lot] = Portfolio(file_path=old_file).positions["INTU"].lots
    assert (lot.date, lot.shares, lot.price_usd) == ("2026-05-30", 12, 300.0)
    assert (lot.market, lot.instrument, lot.label) == ("broker del exterior", "acción",
                                                       "costo promedio migrado")
    assert Portfolio(file_path=old_file).positions["INTU"].notes == "nota"


def test_editing_a_multi_lot_position_keeps_every_lot_and_saves_the_notes(old_file):
    """Q2 (b): con varios lotes, «Editar» no promedia: cambia sólo las notas."""
    p = Portfolio(file_path=old_file)
    p.add_position("MSFT", 10, 100.0, "2026-01-05")
    p.add_position("MSFT", 30, 120.0, "2026-03-02")
    assert p.update_position("MSFT", 99, 1.0, "2020-01-01", "dos compras") is False
    pos = Portfolio(file_path=old_file).positions["MSFT"]
    assert [(lot.date, lot.shares, lot.price_usd) for lot in pos.lots] == [
        ("2026-01-05", 10, 100.0), ("2026-03-02", 30, 120.0),
    ]
    assert pos.notes == "dos compras"
