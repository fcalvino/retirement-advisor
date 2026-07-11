"""Tests for universe data snapshots + effective-universe merge (Item 3)."""

from __future__ import annotations

import pytest

from data.snapshot import (
    SCHEMA,
    export_universe_data_snapshot,
    load_snapshot,
    save_snapshot_to_path,
    snapshot_to_bytes,
)
from data.universe_loader import get_effective_universe, load_universe

# ------------------------------------------------------------------ #
#  get_effective_universe                                            #
# ------------------------------------------------------------------ #

def test_effective_universe_no_customs_equals_base():
    base = load_universe("default")
    tickers, customs = get_effective_universe("default", None)
    assert tickers == base
    assert customs == []


def test_effective_universe_appends_customs():
    base = load_universe("default")
    tickers, customs = get_effective_universe("default", ["ZZZZ", "YYYY"])
    assert tickers[: len(base)] == base          # order preserved
    assert customs == ["ZZZZ", "YYYY"]
    assert tickers[-2:] == ["ZZZZ", "YYYY"]


def test_effective_universe_dedups_against_base():
    base = load_universe("default")
    dup = base[0]
    tickers, customs = get_effective_universe("default", [dup, "ZZZZ"])
    assert dup not in customs
    assert "ZZZZ" in customs


def test_effective_universe_skips_invalid():
    _, customs = get_effective_universe("default", ["bad ticker!", "GOODSYM".lower()])
    assert "bad ticker!".upper() not in customs


# ------------------------------------------------------------------ #
#  Snapshot export/import                                            #
# ------------------------------------------------------------------ #

def _fake_info(sym):
    return {"shortName": f"{sym} Inc", "sector": "Tech", "currentPrice": 100.0,
            "trailingPE": 20.0, "junk_field": "ignored"}


def _fake_price(sym):
    return 123.45


def test_export_snapshot_structure():
    snap = export_universe_data_snapshot(
        ["AAPL", "msft"], info_lookup=_fake_info, price_lookup=_fake_price,
    )
    assert snap["schema"] == SCHEMA
    assert snap["n_tickers"] == 2
    assert set(snap["tickers"]) == {"AAPL", "MSFT"}
    e = snap["tickers"]["AAPL"]
    assert e["price"] == 123.45
    assert e["info"]["shortName"] == "AAPL Inc"
    assert "junk_field" not in e["info"]  # only whitelisted keys captured


def test_export_snapshot_tolerates_lookup_failure():
    def _boom(_sym):
        raise RuntimeError("network down")
    snap = export_universe_data_snapshot(
        ["AAPL"], info_lookup=_boom, price_lookup=_boom,
    )
    assert snap["tickers"]["AAPL"]["info"] == {}
    assert snap["tickers"]["AAPL"]["price"] is None


def test_snapshot_bytes_and_load_roundtrip(tmp_path):
    import json
    snap = export_universe_data_snapshot(["AAPL"], info_lookup=_fake_info, price_lookup=_fake_price)
    data = json.loads(snapshot_to_bytes(snap).decode("utf-8"))
    assert load_snapshot(data)["n_tickers"] == 1
    p = tmp_path / "snap.json"
    save_snapshot_to_path(snap, p)
    assert p.exists()
    assert load_snapshot(json.loads(p.read_text()))["schema"] == SCHEMA


def test_load_snapshot_rejects_garbage():
    with pytest.raises(ValueError):
        load_snapshot({"not": "a snapshot"})
    with pytest.raises(ValueError):
        load_snapshot({"schema": SCHEMA, "tickers": "nope"})
