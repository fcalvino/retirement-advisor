"""LLM-2 oracle: every writer of the track record obeys the same rule.

The committee wrote ``recommendation_log`` with its own rule (AUDIT_LLM_2026-09,
LLM-2): it stored ``total_score`` where every other path stores the score the
decision matrix uses (median gap over 25 same-day pairs: 25 points), and it
logged what the Screener refuses — AIR.PA and NOVN.SW quoted in EUR/CHF (ids
1507, 1509), ABVE with an empty feed (1021) and the symbol ``BTC-USD — BITCOIN``
(1350). Its rows were 5 of the 11 real graded outcomes.

Oracles, independent of the code under test:
  - the score: ``RetirementStrategy().decide()`` on the same (fund, tech) — the
    engine's own ``fundamental_score``;
  - admission: the Screener's rules (``TRACK_RECORD.benchmark_currency``,
    ``is_empty_feed``) and the ticker shape the Stock Analysis input already
    enforces (``is_valid_ticker_symbol``).

Real SQLite stores throughout (project convention: no DB mocks); a fake
``call_fn`` for the panel, so no network.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from analysis.committee import CommitteeAnalyzer
from analysis.eval_cases import golden_cases
from analysis.fundamental import FundamentalResult
from analysis.strategy import RetirementStrategy, effective_decision_score
from analysis.technical import TechnicalResult
from analysis.track_record import TrackRecordStore
from config import TRACK_RECORD
from tests.test_committee import _agent_json, _fundamental_json, make_fake

ROOT = Path(__file__).resolve().parents[1]
COMITE_PAGE = ROOT / "dashboard/views/15_Comite.py"
MIGRATION = ROOT / "scripts/migrations/mark_inadmissible_rows.py"

WRITERS = ("committee", "ai", "rule_based", "screener")


def _base():
    case = golden_cases()[0]  # quality_compounder_buy (MSFT, USD-listed)
    return case.fund, case.tech


def _scale_gap(fund):
    """The measured gap: the engine's score 25 points above ``total_score``."""
    return replace(fund, adjusted_score=fund.total_score + 25.0)


def _all_buy():
    return make_fake(
        fundamental=_fundamental_json("BUY", "HIGH"),
        macro=_agent_json("BUY", "HIGH"),
        devil=_agent_json("BUY", "HIGH"),
        pm=_agent_json("BUY", "HIGH"),
        coach=_agent_json("BUY", "HIGH"),
        dividend=_agent_json("BUY", "HIGH"),
    )


def _verdict(fund, tech):
    return CommitteeAnalyzer(call_fn=_all_buy(), use_cache=False).analyze(fund, tech)


def _empty_feed(symbol="ABVE"):
    fund = FundamentalResult(symbol=symbol)
    fund.data_quality = {"level": "poor", "stale": False}
    return fund, TechnicalResult(symbol=symbol)


@pytest.fixture
def store(tmp_path):
    return TrackRecordStore(db_path=str(tmp_path / "tr.db"))


# --------------------------------------------------------------------------- #
#  1. Scale — the committee stores the score the engine decides with           #
# --------------------------------------------------------------------------- #

def test_precondition_the_two_scores_differ():
    fund = _scale_gap(_base()[0])
    assert fund.adjusted_score - fund.total_score == 25.0
    assert effective_decision_score(fund) == fund.adjusted_score


def test_committee_score_is_the_engine_score():
    fund, tech = _base()
    fund = _scale_gap(fund)
    engine = RetirementStrategy().decide(fund, tech)
    logged = _verdict(fund, tech).to_decision(fund, tech)
    assert logged.fundamental_score == engine.fundamental_score
    assert logged.fundamental_score == effective_decision_score(fund)


def test_committee_score_is_the_engine_score_for_crypto_too():
    case = next(c for c in golden_cases() if c.fund.is_crypto)
    engine = RetirementStrategy().decide(case.fund, case.tech)
    logged = _verdict(case.fund, case.tech).to_decision(case.fund, case.tech)
    assert logged.fundamental_score == engine.fundamental_score


def test_committee_row_lands_on_the_engine_scale(store):
    fund, tech = _base()
    fund = _scale_gap(fund)
    rec_id = store.log_recommendation(
        _verdict(fund, tech).to_decision(fund, tech), source="committee", fundamental=fund,
    )
    assert rec_id is not None
    row = store.get_recommendations()[0]
    assert row.fundamental_score == effective_decision_score(fund)


# --------------------------------------------------------------------------- #
#  2. Admission — one gate, whatever the source                                #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("source", WRITERS)
@pytest.mark.parametrize("symbol,ccy", [("AIR.PA", "EUR"), ("NOVN.SW", "CHF"), ("7203.T", "JPY")])
def test_non_benchmark_currency_is_not_written(store, source, symbol, ccy):
    fund, tech = _base()
    fund = replace(fund, symbol=symbol, currency=ccy)
    decision = RetirementStrategy().decide(fund, tech)
    assert ccy != TRACK_RECORD.benchmark_currency
    assert store.log_recommendation(decision, source=source, fundamental=fund) is None
    assert store.get_recommendations() == []


@pytest.mark.parametrize("source", WRITERS)
def test_empty_feed_is_not_written(store, source):
    fund, tech = _empty_feed()
    decision = RetirementStrategy().decide(fund, tech)
    assert decision.action == "SELL"  # what would have been published
    assert store.log_recommendation(decision, source=source, fundamental=fund) is None
    assert store.get_recommendations() == []


@pytest.mark.parametrize("source", WRITERS)
def test_a_symbol_that_is_not_a_ticker_is_not_written(store, source):
    fund, tech = _base()
    decision = RetirementStrategy().decide(fund, tech)
    decision.symbol = "BTC-USD — BITCOIN"  # id 1350
    assert store.log_recommendation(decision, source=source, fundamental=fund) is None
    assert store.get_recommendations() == []


@pytest.mark.parametrize("source", WRITERS)
@pytest.mark.parametrize("ccy", ["USD", ""])
def test_admissible_rows_are_still_written(store, source, ccy):
    """Control: USD, and a currency nobody recorded (pre-field rows, alerts)."""
    fund, tech = _base()
    fund = replace(fund, currency=ccy)
    decision = RetirementStrategy().decide(fund, tech)
    assert store.log_recommendation(decision, source=source, fundamental=fund) is not None


def test_a_writer_without_a_fundamental_is_still_written(store):
    """The alert engine logs with a sector-only stand-in: no currency, no price."""
    from types import SimpleNamespace

    decision = SimpleNamespace(symbol="MSFT", action="BUY", confidence="MEDIUM",
                               fundamental_score=70.0, technical_signal="", rationale=[])
    assert store.log_recommendation(
        decision, source="rule_based", fundamental=SimpleNamespace(sector="Technology"),
    ) is not None


@pytest.mark.parametrize("ccy,written", [("EUR", 0), ("USD", 1), ("", 1)])
def test_the_alert_engine_passes_the_quote_currency_to_the_gate(monkeypatch, store, tmp_path,
                                                                ccy, written):
    from alerts.engine import AlertEngine
    from alerts.store import AlertStore
    from analysis import track_record

    monkeypatch.setattr(track_record, "track_record_store", store)
    engine = AlertEngine(store=AlertStore(db_path=str(tmp_path / "alerts.db")))
    engine._log_track_record("AIR.PA", "BUY", 70.0, "Industrials", ccy)
    assert len(store.get_recommendations()) == written


# --------------------------------------------------------------------------- #
#  3. The Comité page — end to end                                             #
# --------------------------------------------------------------------------- #

def _comite(monkeypatch, store, fund, tech, typed=None):
    from analysis import committee, track_record
    from dashboard import shared

    verdict = _verdict(fund, tech) if fund.current_price else None
    convened = []

    def _analyze(self, *a, **kw):
        convened.append(a)
        return verdict

    monkeypatch.setattr(shared, "cached_full_analysis", lambda *a, **kw: (fund, tech, None))
    monkeypatch.setattr(committee.CommitteeAnalyzer, "analyze", _analyze)
    monkeypatch.setattr(track_record, "track_record_store", store)
    app = AppTest.from_file(str(COMITE_PAGE), default_timeout=30)
    for key, value in dict(ai_enabled=True, ai_provider="groq",
                           ai_model="openai/gpt-oss-120b", ai_api_key="test-key").items():
        app.session_state[key] = value
    app.session_state["comite_symbol_input"] = typed or fund.symbol
    app.run()
    next(b for b in app.button if "Convocar" in b.label).click().run()
    assert not app.exception
    return app, convened


def _text(app):
    return " ".join(e.value for e in (*app.markdown, *app.caption, *app.error,
                                      *app.warning, *app.info))


def test_comite_page_logs_a_usd_verdict_on_the_engine_scale(monkeypatch, store):
    fund, tech = _base()
    fund = replace(_scale_gap(fund), currency="USD")
    app, _ = _comite(monkeypatch, store, fund, tech)
    rows = store.get_recommendations()
    assert [r.source for r in rows] == ["committee"]
    assert rows[0].fundamental_score == effective_decision_score(fund)
    assert "quedó registrado en el Track Record" in _text(app)


def test_comite_page_does_not_claim_a_row_the_store_deduped(monkeypatch, store):
    """QA LLM-2: the dedup key has no ``source``, so a verdict matching what the
    Screener already logged today writes nothing (INTU HOLD, 2026-09-22, hidden by
    row 1364). The caption must say what happened in the store, not what was tried.
    """
    fund, tech = _base()
    fund = replace(fund, currency="USD")
    action = _verdict(fund, tech).to_decision(fund, tech).action
    seeded = RetirementStrategy().decide(fund, tech)
    seeded.action = action
    assert store.log_recommendation(seeded, source="screener", fundamental=fund) is not None

    app, _ = _comite(monkeypatch, store, fund, tech)
    assert [r.source for r in store.get_recommendations()] == ["screener"]
    text = _text(app)
    assert "quedó registrado" not in text
    assert f"ya hay un {action} de MSFT registrado hoy" in text


def test_comite_page_does_not_claim_a_row_when_logging_fails(monkeypatch, store):
    fund, tech = _base()
    fund = replace(fund, currency="USD")
    monkeypatch.setattr(store, "log_recommendation", lambda *a, **kw: None)
    app, _ = _comite(monkeypatch, store, fund, tech)
    text = _text(app)
    assert "quedó registrado" not in text
    assert "No se pudo registrar" in text


def test_comite_page_does_not_log_a_foreign_quote_and_says_so(monkeypatch, store):
    fund, tech = _base()
    fund = replace(fund, symbol="AIR.PA", currency="EUR")
    app, convened = _comite(monkeypatch, store, fund, tech)
    assert convened  # the panel still deliberates — only the evidence is gated
    assert store.get_recommendations() == []
    text = _text(app)
    assert "Dictamen AIR.PA" in text
    assert "quedó registrado" not in text
    assert "No se registra en el Track Record" in text and "EUR" in text


def test_comite_page_does_not_convene_on_an_empty_feed(monkeypatch, store):
    fund, tech = _empty_feed()
    app, convened = _comite(monkeypatch, store, fund, tech)
    assert convened == []  # no LLM round-trips on a failed fetch
    assert store.get_recommendations() == []
    assert any("No hay datos para **ABVE**" in e.value for e in app.error)


def test_comite_page_rejects_a_symbol_that_is_not_a_ticker(monkeypatch, store):
    fund, tech = _base()
    app, convened = _comite(monkeypatch, store, fund, tech, typed="BTC-USD — BITCOIN")
    assert convened == []
    assert store.get_recommendations() == []
    assert any("no tiene forma de ticker" in e.value for e in app.error)


# --------------------------------------------------------------------------- #
#  4. The four historical rows — marked, not deleted                           #
# --------------------------------------------------------------------------- #

def _load_migration():
    spec = importlib.util.spec_from_file_location("mark_inadmissible_rows", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(store, rows):
    """Write rows with explicit ids, bypassing the gate — they predate it."""
    from analysis.track_record import RecommendationLog
    from data.clock import utc_now

    with store._Session() as s:
        for row_id, symbol, source in rows:
            s.add(RecommendationLog(id=row_id, symbol=symbol, action="BUY", confidence="MEDIUM",
                                    fundamental_score=60.0, source=source, created_at=utc_now()))
        s.commit()


_HISTORICAL = [(1021, "ABVE", "committee"), (1350, "BTC-USD — BITCOIN", "committee"),
               (1507, "AIR.PA", "committee"), (1509, "NOVN.SW", "committee")]
_DECOY = (1508, "AIR.PA", "screener")  # same symbol, same day, another writer


def test_the_migration_ships_the_four_audited_ids():
    mod = _load_migration()
    assert mod.INADMISSIBLE_ROW_IDS == (1021, 1350, 1507, 1509)
    assert mod.EXPECTED_SOURCE_BEFORE == "committee"


def test_dry_run_is_the_default_and_writes_nothing(store):
    mod = _load_migration()
    _seed(store, _HISTORICAL)
    report = mod.mark_inadmissible_rows(store)
    assert report["dry_run"] and report["marked"] == 4
    assert {r.source for r in store.get_recommendations()} == {"committee"}


def test_marked_rows_leave_every_read_and_the_decoy_stays(store):
    from datetime import timedelta

    from analysis.track_record import INADMISSIBLE_SOURCE

    mod = _load_migration()
    _seed(store, [*_HISTORICAL, _DECOY])
    report = mod.mark_inadmissible_rows(store, dry_run=False)
    assert report["marked"] == 4

    assert [r.id for r in store.get_recommendations()] == [1508]
    audit = store.get_recommendations(include_fixtures=True)
    assert {r.id for r in audit if r.source == INADMISSIBLE_SOURCE} == {1021, 1350, 1507, 1509}

    later = store.get_recommendations(include_fixtures=True)[0].created_at + timedelta(days=400)
    assert [r.id for r in store.get_pending_scoring(30, now=later)] == [1508]

    for row_id in (1507, 1508):
        store.save_outcome(rec_id=row_id, horizon_days=30, price_at_horizon=1.0, return_pct=1.0,
                           benchmark_return_pct=1.0, excess_return_pct=0.0, hit=True)
    assert [r["rec_id"] for r in store.get_scored_rows(30)] == [1508]

    again = mod.mark_inadmissible_rows(store, dry_run=False)
    assert again["marked"] == 0 and again["already_marked"] == 4


def test_an_unexpected_source_aborts_without_writing(store):
    mod = _load_migration()
    _seed(store, [*_HISTORICAL[:3], (1509, "NOVN.SW", "screener")])
    with pytest.raises(mod.UnexpectedRowError):
        mod.mark_inadmissible_rows(store, dry_run=False)
    assert {r.source for r in store.get_recommendations()} == {"committee", "screener"}
