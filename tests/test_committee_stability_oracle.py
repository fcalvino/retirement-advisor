"""#151 — cuánto cambia el dictamen del comité entre corridas con el mismo input.

Oráculo: las métricas se comparan contra valores calculados a mano y contra
``statistics``, no contra otra llamada al módulo. El banco corre sin red y sin
caché, con el modelo inyectado.
"""

import json
import statistics
from datetime import datetime

import pytest

from analysis.committee_stability import (
    StabilityRecord,
    record_from_dict,
    run_stability,
    summarize_stability,
)
from analysis.eval_cases import stability_cases
from analysis.eval_harness import CommitteeProvider

NOW = datetime(2026, 9, 28, 12, 0, 0)


def _rec(case_id="stability_ko", run=0, action="HOLD", final=None, lean=0.0, complete=True,
         stances=None, provider="committee:groq/m"):
    return StabilityRecord(
        case_id=case_id, run=run, provider=provider,
        action=action, final_action=final or action, lean=lean, confidence="MEDIUM",
        stances=stances or {}, complete=complete, quorum_pct=100.0 if complete else 60.0,
        failure_causes=[] if complete else ["rate_limit"], abstentions={}, error="",
    )


# --------------------------------------------------------------------------- #
#  Métricas                                                                   #
# --------------------------------------------------------------------------- #

def test_change_rate_counts_only_complete_runs():
    recs = [_rec(run=0, action="BUY", lean=0.40), _rec(run=1, action="BUY", lean=0.35),
            _rec(run=2, action="HOLD", lean=0.10), _rec(run=3, action="BUY", lean=0.45),
            # a rate-limited panel is not the model changing its mind
            _rec(run=4, action="SELL", lean=-0.9, complete=False)]
    case = summarize_stability(recs)["cases"]["stability_ko"]

    assert case["n_runs"] == 5
    assert case["n_complete"] == 4
    assert case["n_incomplete"] == 1
    assert case["action"]["modal"] == "BUY"
    assert case["action"]["change_rate"] == pytest.approx(0.25)
    assert case["action"]["distinct"] == 2
    assert case["action"]["counts"] == {"BUY": 3, "HOLD": 1}
    leans = [0.40, 0.35, 0.10, 0.45]
    assert case["lean"]["mean"] == pytest.approx(statistics.mean(leans))
    assert case["lean"]["stdev"] == pytest.approx(statistics.stdev(leans))
    assert case["lean"]["min"] == pytest.approx(0.10)
    assert case["lean"]["max"] == pytest.approx(0.45)


def test_raw_and_final_action_are_measured_apart():
    # The overlay floors the vote: a panel that flips BUY/HOLD can still land on
    # HOLD every time. Both numbers matter — one is the model, the other the user.
    recs = [_rec(run=0, action="BUY", final="HOLD"), _rec(run=1, action="HOLD", final="HOLD")]
    case = summarize_stability(recs)["cases"]["stability_ko"]
    assert case["action"]["change_rate"] == pytest.approx(0.5)
    assert case["final_action"]["change_rate"] == pytest.approx(0.0)
    assert case["final_action"]["modal"] == "HOLD"


def test_single_complete_run_has_no_spread_and_no_complete_run_has_no_metrics():
    one = summarize_stability([_rec(lean=0.2)])["cases"]["stability_ko"]
    assert one["lean"]["stdev"] is None           # n=1: not measured, not 0
    assert one["action"]["change_rate"] == 0.0

    none_ok = summarize_stability([_rec(complete=False)])["cases"]["stability_ko"]
    assert none_ok["n_complete"] == 0
    assert none_ok["action"]["change_rate"] is None
    assert none_ok["lean"]["mean"] is None


def test_voice_agreement_per_role():
    recs = [
        _rec(run=0, stances={"Abogado del Diablo": "SELL", "Portfolio Manager": "HOLD"}),
        _rec(run=1, stances={"Abogado del Diablo": "REDUCE", "Portfolio Manager": "HOLD"}),
        _rec(run=2, stances={"Abogado del Diablo": "SELL", "Portfolio Manager": "HOLD"}),
    ]
    roles = summarize_stability(recs)["cases"]["stability_ko"]["roles"]
    assert roles["Portfolio Manager"] == {"modal": "HOLD", "agreement": 1.0, "distinct": 1, "n": 3}
    assert roles["Abogado del Diablo"]["modal"] == "SELL"
    assert roles["Abogado del Diablo"]["agreement"] == pytest.approx(2 / 3)
    assert roles["Abogado del Diablo"]["distinct"] == 2


def test_bank_totals_and_grouping_by_provider():
    recs = [_rec(case_id="a", run=0, action="BUY"), _rec(case_id="a", run=1, action="HOLD"),
            _rec(case_id="b", run=0, action="HOLD"), _rec(case_id="b", run=1, action="HOLD"),
            _rec(case_id="a", run=0, action="BUY", provider="committee:claude/x")]
    out = summarize_stability(recs)
    groq = out["by_provider"]["committee:groq/m"]
    assert groq["n_cases"] == 2
    assert groq["cases_with_action_change"] == 1
    assert groq["mean_action_change_rate"] == pytest.approx((0.5 + 0.0) / 2)
    assert groq["n_complete"] == 4
    assert out["by_provider"]["committee:claude/x"]["n_cases"] == 1
    # `cases` is the primary provider's view only when there is one provider
    assert set(out["cases"]) == set()


def test_record_round_trips_through_json():
    r = _rec(stances={"Behavioral Coach": "HOLD"})
    assert record_from_dict(json.loads(json.dumps(r.to_dict()))) == r


# --------------------------------------------------------------------------- #
#  El banco                                                                   #
# --------------------------------------------------------------------------- #

def _cycling_call(runs_seen):
    """A model that votes BUY on even runs and HOLD on odd ones, for every voice."""
    def call(prompt):
        stance = "BUY" if runs_seen[0] % 2 == 0 else "HOLD"
        if "Abogado del Diablo" in prompt or "Portfolio Manager" in prompt \
                or "Behavioral Coach" in prompt or "Estratega Macro" in prompt \
                or "Analista de Dividendo" in prompt:
            return json.dumps({"stance": stance, "confidence": "MEDIUM",
                               "key_points": ["p"], "concerns": ["c"]})
        return json.dumps({"action": stance, "confidence": "MEDIUM",
                           "reasoning": "r" * 100, "rationale": ["x"], "risks": ["y"],
                           "macro_factors": []})
    return call


def test_six_frozen_cases_four_equity_two_crypto_all_with_macro():
    cases = stability_cases(now=NOW)
    assert [c.case_id for c in cases] == [
        "stability_msft", "stability_ko", "stability_xyz", "stability_ypf",
        "stability_btc", "stability_eth"]
    assert sum(bool(c.fund.is_crypto) for c in cases) == 2
    assert all(c.macro_context for c in cases)
    assert all(not c.headlines for c in cases if c.fund.is_crypto)
    # frozen: same instant, same facts
    assert [c.macro_context for c in stability_cases(now=NOW)] == [c.macro_context for c in cases]


def test_run_stability_measures_the_injected_model(monkeypatch):
    import analysis.committee as committee_mod

    def no_cache(*_a, **_k):
        raise AssertionError("el banco de estabilidad no puede tocar la caché del comité")

    monkeypatch.setattr(committee_mod.CommitteeAnalyzer, "_get_cached", no_cache)
    monkeypatch.setattr(committee_mod.CommitteeAnalyzer, "_set_cached", no_cache)

    runs_seen = [0]
    provider = CommitteeProvider(call_fn=_cycling_call(runs_seen))
    cases = [c for c in stability_cases(now=NOW) if c.case_id in ("stability_ko", "stability_btc")]
    written = []

    def on_record(rec):
        written.append(rec)
        if rec.case_id == cases[-1].case_id:
            runs_seen[0] += 1

    recs = run_stability(provider, cases, runs=3, on_record=on_record)

    assert written == recs
    assert [(r.case_id, r.run) for r in recs] == [
        ("stability_ko", 0), ("stability_btc", 0), ("stability_ko", 1),
        ("stability_btc", 1), ("stability_ko", 2), ("stability_btc", 2)]
    ko = [r for r in recs if r.case_id == "stability_ko"]
    assert [r.action for r in ko] == ["BUY", "HOLD", "BUY"]
    assert all(r.complete for r in recs)
    # crypto convenes no dividend voice; every case convenes the Macro
    btc = next(r for r in recs if r.case_id == "stability_btc")
    assert "Analista de Dividendo" not in btc.stances
    assert all("Estratega Macro" in r.stances for r in recs)
    assert "Analista de Dividendo" in ko[0].stances

    summary = summarize_stability(recs)["cases"]["stability_ko"]
    assert summary["action"]["change_rate"] == pytest.approx(1 / 3)


def test_run_stability_resumes_and_survives_a_provider_error():
    class Flaky:
        name = "committee:fake/m"

        def get_verdict(self, case):
            raise RuntimeError("boom")

    cases = stability_cases(now=NOW)[:2]
    recs = run_stability(Flaky(), cases, runs=2, done={("stability_msft", 0)})
    assert [(r.case_id, r.run) for r in recs] == [
        ("stability_ko", 0), ("stability_msft", 1), ("stability_ko", 1)]
    assert all(not r.complete and r.action == "ERROR" and "boom" in r.error for r in recs)


def test_committee_stability_bank_does_not_read_the_live_feed(monkeypatch):
    import analysis.committee as committee_mod

    def boom(*_a, **_k):
        raise AssertionError("el banco no puede leer el feed ni el RAG")

    monkeypatch.setattr(committee_mod, "_ticker_news", boom)
    monkeypatch.setattr(committee_mod, "_ticker_drawdowns", boom)
    provider = CommitteeProvider(call_fn=_cycling_call([0]))
    recs = run_stability(provider, stability_cases(now=NOW)[:1], runs=1)
    assert recs[0].complete


# --------------------------------------------------------------------------- #
#  El script                                                                  #
# --------------------------------------------------------------------------- #

def _script():
    import scripts.committee_stability as script
    return script


def test_dry_run_makes_no_call(monkeypatch, capsys, tmp_path):
    script = _script()

    def boom(*_a, **_k):
        raise AssertionError("la corrida en seco no puede llamar al modelo")

    monkeypatch.setattr(script, "run_stability", boom)
    assert script.main(["--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "stability_msft" in out and "Llamadas estimadas" in out
    assert list(tmp_path.iterdir()) == []


def test_live_refuses_a_dirty_tree(monkeypatch, tmp_path):
    script = _script()
    monkeypatch.setattr(script, "_git_sha", lambda: "abc1234-dirty")
    monkeypatch.setattr(script, "_live_config", lambda: object())
    with pytest.raises(SystemExit):
        script.main(["--live", "--out-dir", str(tmp_path)])
    assert list(tmp_path.iterdir()) == []


def test_live_run_writes_jsonl_as_it_goes_and_resumes(monkeypatch, tmp_path):
    script = _script()
    monkeypatch.setattr(script, "_git_sha", lambda: "abc1234")
    monkeypatch.setattr(script, "_live_config", lambda: object())
    runs_seen = [0]
    monkeypatch.setattr(script, "_provider",
                        lambda _cfg: CommitteeProvider(call_fn=_cycling_call(runs_seen)))

    assert script.main(["--live", "--runs", "2", "--cases", "stability_ko",
                        "--out-dir", str(tmp_path)]) == 0
    jsonl = next(tmp_path.glob("*_stability_*.jsonl"))
    lines = [json.loads(line) for line in jsonl.read_text().splitlines()]
    assert lines[0]["kind"] == "header" and lines[0]["frozen_at"]
    assert [ln["run"] for ln in lines[1:]] == [0, 1]
    report = json.loads(next(tmp_path.glob("*_stability_*.json")).read_text())
    assert report["bank"] == "stability"
    assert report["git_sha"] == "abc1234"
    assert report["n_records"] == 2
    assert "usage" in report and "summary" in report

    # resuming a finished file adds nothing
    calls = []
    monkeypatch.setattr(script, "_provider", lambda _cfg: CommitteeProvider(
        call_fn=lambda p: calls.append(p) or _cycling_call([0])(p)))
    assert script.main(["--live", "--resume", str(jsonl)]) == 0
    assert calls == []
    assert len(jsonl.read_text().splitlines()) == 3
