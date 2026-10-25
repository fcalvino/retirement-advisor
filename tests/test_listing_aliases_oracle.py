"""ADR en el universo global, y un ticker local leído como su ADR (LISTING_ALIASES).

Sin red. La tabla es un dato medido (yfinance, 2026-10-24); lo que este archivo cuida
son sus invariantes y que el alias se aplique al leer sin reescribir lo guardado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import LISTING_ALIASES, UNIVERSE
from data import universe_loader
from data.listing_aliases import resolve_listing, resolve_weights
from data.plan_context import drift_breakdown, session_plan_is_unsaved_target
from data.plan_store import PlanSnapshot, PlanStore

_UNIVERSES = Path(universe_loader.__file__).parent / "universes"


def _symbols(key: str) -> list[str]:
    return list(universe_loader.load_universe(key))


def test_alias_table_shape():
    suffixes = {s for s in UNIVERSE.exchange_suffixes if s}
    for local, (adr, units) in LISTING_ALIASES.aliases.items():
        assert any(local.endswith(s) for s in suffixes), f"{local} no es un listado local"
        assert "." not in adr, f"{adr} lleva sufijo de bolsa: no es un listado en EE.UU."
        assert units >= 1.0, f"{local}: la razón son acciones locales por ADR, no al revés"
    adrs = [adr for adr, _ in LISTING_ALIASES.aliases.values()]
    assert len(adrs) == len(set(adrs)), "dos listados locales no pueden compartir ADR"


def test_global_universe_lists_the_adr_not_the_local_ticker():
    glob, latam = set(_symbols("global_quality")), set(_symbols("latam_adrs"))
    for local, (adr, _) in LISTING_ALIASES.aliases.items():
        assert local not in glob, f"{local} sigue como listado local"
        assert adr in glob | latam, f"{adr} no está en ningún universo"


def test_adr_already_in_latam_is_not_duplicated_into_global():
    glob, latam = set(_symbols("global_quality")), set(_symbols("latam_adrs"))
    assert "SQM" in latam and "SQM" not in glob
    assert not glob & latam


def test_global_universe_has_no_duplicate_tickers():
    raw = json.loads((_UNIVERSES / "global_quality.json").read_text(encoding="utf-8"))
    tickers = [t["ticker"] for t in raw["tickers"]]
    assert len(tickers) == len(set(tickers))
    assert str(len(tickers)) in raw["description"], "la descripción dice otro tamaño"


def test_resolve_listing():
    assert resolve_listing("SHEL.L") == "SHEL"
    assert resolve_listing("shel.l") == "SHEL"
    assert resolve_listing("SHEL") == "SHEL"
    assert resolve_listing("7203.T") == "7203.T"  # grupo B: sin ADR aprobado
    assert resolve_listing("MC.PA") == "MC.PA"    # solo OTC: se queda local


def test_resolve_weights_sums_local_and_adr_under_one_symbol():
    got = resolve_weights({"BHP.AX": 10.0, "BHP": 5.0, "AAPL": 85.0})
    assert got == {"BHP": 15.0, "AAPL": 85.0}
    assert sum(got.values()) == pytest.approx(100.0)


def _snapshot(path: Path, allocation: list[dict]) -> PlanSnapshot:
    snap = PlanSnapshot(id="p", name="P", created_at="2026-10-24", updated_at="2026-10-24",
                        allocation=allocation)
    PlanStore(path).upsert(snap)
    return PlanStore(path).get("p")


def test_saved_plan_with_local_ticker_targets_the_adr_without_rewriting_the_file(tmp_path):
    path = tmp_path / "plans.json"
    snap = _snapshot(path, [{"symbol": "BHP.AX", "weight_pct": 30.0},
                            {"symbol": "NOVN.SW", "weight_pct": 20.0},
                            {"symbol": "AAPL", "weight_pct": 50.0}])
    before = path.read_text(encoding="utf-8")
    assert snap.target_weights() == {"BHP": 30.0, "NVS": 20.0, "AAPL": 50.0}
    assert path.read_text(encoding="utf-8") == before
    assert [a["symbol"] for a in PlanStore(path).get("p").allocation][0] == "BHP.AX"


def test_core_holdings_fallback_is_resolved_too(tmp_path):
    snap = PlanSnapshot(id="p", name="P", created_at="x", updated_at="x",
                        core_holdings=[{"symbol": "SHEL.L", "suggested_weight_pct": 40.0}])
    assert snap.target_weights() == {"SHEL": 40.0}


def test_drift_counts_local_and_adr_as_one_row():
    """El plan dice BHP.AX y el tracker BHP (o al revés): sin deriva, no dos filas."""
    for target, actual in (({"BHP.AX": 30.0, "AAPL": 70.0}, {"BHP": 30.0, "AAPL": 70.0}),
                           ({"BHP": 30.0, "AAPL": 70.0}, {"BHP.AX": 30.0, "AAPL": 70.0})):
        got = drift_breakdown(target, actual)
        assert got["symbols"] == ["AAPL", "BHP"]
        assert got["total_drift_pct"] == pytest.approx(0.0)


def test_drift_without_alias_is_unchanged():
    got = drift_breakdown({"7203.T": 50.0, "AAPL": 50.0}, {"TM": 50.0, "AAPL": 50.0})
    assert got["symbols"] == ["7203.T", "AAPL", "TM"]  # grupo B: sin alias, siguen distintos
    assert got["total_drift_pct"] == pytest.approx(50.0)


def test_session_run_with_local_ticker_matches_the_saved_plan(tmp_path):
    from types import SimpleNamespace
    snap = _snapshot(tmp_path / "plans.json", [{"symbol": "SHEL.L", "weight_pct": 40.0},
                                               {"symbol": "AAPL", "weight_pct": 60.0}])
    tickers = [SimpleNamespace(symbol="SHEL", weight_pct=40.0), SimpleNamespace(symbol="AAPL", weight_pct=60.0)]
    assert session_plan_is_unsaved_target(SimpleNamespace(tickers=tickers), snap) is False


def test_committee_finds_the_plan_row_for_a_local_ticker():
    """Analizar BHP.AX con un plan que dice BHP.AX: la fila de deriva no se pierde."""
    from types import SimpleNamespace

    from analysis.committee import build_ticker_portfolio_context

    plan = SimpleNamespace(name="P", target_weights=lambda: {"BHP.AX": 30.0})
    ctx = build_ticker_portfolio_context(
        "BHP.AX", "Basic Materials",
        position_weights={"BHP.AX": 10.0, "AAPL": 90.0}, active_plan=plan,
    )
    assert ctx["plan_target_pct"] == 30.0
    assert ctx["drift_pct"] == pytest.approx(-20.0)
