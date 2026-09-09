"""Oracles for filing evidence pack + unsourced-catalyst policy (ideas 5 + 9).

No live SEC/API. A retrieve that invents a ratio or a catalyst without a
snippet in the fixture must fail these tests — not a round-trip against the
implementation's own parser.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from analysis.filing_evidence import (
    EMPTY_CATALYSTS_BODY,
    FilingEvidencePack,
    FilingSnippet,
    citation_matches_pack,
    empty_pack,
    filing_panel_state,
    filter_cited_catalysts,
    replace_catalysts_section,
)
from analysis.moat import MoatAnalyzer, MoatDetail
from analysis.strategy import (
    Decision,
    apply_unsourced_catalyst_policy,
)
from config import FILING_EVIDENCE
from data.sec_filings import extract_item_section, retrieve_filing_pack

# Independent 10-K-shaped HTML: Item 7 must contain Product X and must not
# leak Item 8's "FINANCIAL STATEMENTS" into the MD&A extract.
_ITEM7_HTML = """
<html><body>
<div>ITEM 1. BUSINESS</div>
<p>We sell widgets with switching costs from our installed base of 12 million users.</p>
<div>ITEM 1A. RISK FACTORS</div>
<p>Competition may reduce margins next year.</p>
<div>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS</div>
<p>We expect to launch Product X in the next twelve months, which we believe will drive revenue.</p>
<div>ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA</div>
<p>See audited financial statements. This sentence is not MD&amp;A.</p>
</body></html>
"""


def _snippet(**kw) -> FilingSnippet:
    defaults = dict(
        form="10-K",
        filed=date(2024, 10, 31),
        accession="0000320193-24-000123",
        item="Item 7",
        kind="catalyst",
        text="We expect to launch Product X in the next twelve months.",
    )
    defaults.update(kw)
    return FilingSnippet(**defaults)


def test_extract_item_7_contains_mda_not_item_8():
    body = extract_item_section(_ITEM7_HTML, "7")
    assert "Product X" in body
    assert "FINANCIAL STATEMENTS" not in body.upper()


def test_extract_item_1_stops_before_1a():
    body = extract_item_section(_ITEM7_HTML, "1")
    assert "12 million users" in body
    assert "RISK FACTORS" not in body.upper()


def test_replace_catalysts_strips_invented_event():
    reasoning = (
        "Tesis: negocio sólido. Riesgos: valuación. "
        "Catalizadores: IPO de una subsidiaria inventada en Q3. "
        "Asignación: 8%."
    )
    out = replace_catalysts_section(reasoning, EMPTY_CATALYSTS_BODY)
    assert "IPO" not in out
    assert "ninguno citado" in out
    assert "Asignación: 8%" in out


def test_empty_retrieve_caps_invented_high_catalysts():
    pack = empty_pack("AAPL", "fetch_failed")
    d = Decision(
        symbol="AAPL",
        action="STRONG BUY",
        confidence="HIGH",
        ai_reasoning=(
            "Tesis: moat wide. Catalizadores: split de 4-for-1 y un buyback récord. "
            "Asignación: 12%."
        ),
        catalysts=[
            {"claim": "split de 4-for-1", "citation": "memoria del modelo"},
        ],
    )
    apply_unsourced_catalyst_policy(d, pack)
    assert d.catalysts == []
    assert d.confidence == FILING_EVIDENCE.no_source_max_confidence
    assert "split" not in (d.ai_reasoning or "").lower()
    assert "ninguno citado" in d.ai_reasoning
    apply_unsourced_catalyst_policy(d, pack)
    assert d.rationale.count("Catalizadores vaciados: no hay filing citable") == 1


def test_pack_present_keeps_only_cited_catalysts():
    pack = FilingEvidencePack(
        symbol="AAPL",
        snippets=[_snippet()],
    )
    d = Decision(
        symbol="AAPL",
        action="BUY",
        confidence="HIGH",
        catalysts=[
            {
                "claim": "Product X launch",
                "citation": "10-K Item 7 filed 2024-10-31",
            },
            {
                "claim": "compra de un unicornio",
                "citation": "conocimiento actual del modelo",
            },
        ],
    )
    apply_unsourced_catalyst_policy(d, pack)
    assert len(d.catalysts) == 1
    assert d.catalysts[0]["claim"] == "Product X launch"
    assert d.confidence == "HIGH"


def test_unmatched_citations_cap_like_empty_pack():
    pack = FilingEvidencePack(symbol="AAPL", snippets=[_snippet()])
    d = Decision(
        symbol="AAPL",
        action="BUY",
        confidence="HIGH",
        catalysts=[{"claim": "evento inventado", "citation": "twitter"}],
        ai_reasoning="Catalizadores: evento inventado. Asignación: 5%.",
    )
    apply_unsourced_catalyst_policy(d, pack)
    assert d.catalysts == []
    assert d.confidence == "LOW"


def test_none_pack_is_noop_for_rule_based():
    d = Decision(symbol="AAPL", action="BUY", confidence="HIGH")
    apply_unsourced_catalyst_policy(d, None)
    assert d.confidence == "HIGH"
    assert d.catalysts == []
    assert d.ai_reasoning == ""


def test_crypto_empty_pack_caps():
    pack = empty_pack("BTC-USD", "crypto")
    d = Decision(
        symbol="BTC-USD",
        action="BUY",
        confidence="HIGH",
        catalysts=[{"claim": "ETF approval mañana", "citation": ""}],
        ai_reasoning="Catalizadores: ETF approval mañana.",
    )
    apply_unsourced_catalyst_policy(d, pack)
    assert d.catalysts == []
    assert d.confidence == "LOW"


def test_citation_matches_form_item_accession():
    pack = FilingEvidencePack(symbol="AAPL", snippets=[_snippet()])
    assert citation_matches_pack("10-K Item 7", pack)
    assert citation_matches_pack("0000320193-24-000123", pack)
    assert not citation_matches_pack("un rumor", pack)


def test_retrieve_no_cik_empty_without_http():
    pack = retrieve_filing_pack(
        "GGAL",
        resolve_cik=lambda _s: None,
        http_get=lambda _u: (_ for _ in ()).throw(AssertionError("no HTTP")),
        use_cache=False,
    )
    assert pack.snippets == []
    assert pack.empty_reason == "no_cik"


def test_retrieve_crypto_skips_edgar():
    pack = retrieve_filing_pack(
        "BTC-USD",
        is_crypto=True,
        http_get=lambda _u: (_ for _ in ()).throw(AssertionError("no HTTP")),
        use_cache=False,
    )
    assert pack.empty_reason == "crypto"


def test_retrieve_builds_snippets_from_fixture_http():
    def fake_get(url: str):
        if "submissions" in url:
            return (
                '{"filings":{"recent":{'
                '"form":["10-K"],'
                '"accessionNumber":["0000320193-24-000123"],'
                '"filingDate":["2024-10-31"],'
                '"primaryDocument":["aapl-20240928.htm"]}}}'
            )
        if url.endswith("aapl-20240928.htm"):
            return _ITEM7_HTML
        raise AssertionError(url)

    pack = retrieve_filing_pack(
        "AAPL",
        http_get=fake_get,
        resolve_cik=lambda _s: 320193,
        use_cache=False,
    )
    assert pack.has_catalyst_source
    texts = " ".join(s.text for s in pack.snippets)
    assert "Product X" in texts
    assert all(s.accession == "0000320193-24-000123" for s in pack.snippets)


def test_filter_drops_uncited():
    pack = FilingEvidencePack(symbol="AAPL", snippets=[_snippet()])
    kept = filter_cited_catalysts(
        [
            {"claim": "Product X", "citation": "Item 7"},
            {"claim": "alien merger", "citation": "dreams"},
        ],
        pack,
    )
    assert [c["claim"] for c in kept] == ["Product X"]


def test_moat_ai_leaves_quant_dims_identical():
    quant = MoatDetail(
        gross_margin_level=2.0,
        gross_margin_stability=1.5,
        roic_sustained=2.0,
        revenue_defensiveness=1.0,
        fcf_conversion=1.5,
        fcf_margin=1.0,
        quant_total=9.0,
    )
    snapshot = (
        quant.gross_margin_level,
        quant.gross_margin_stability,
        quant.roic_sustained,
        quant.revenue_defensiveness,
        quant.fcf_conversion,
        quant.fcf_margin,
        quant.quant_total,
    )
    pack = FilingEvidencePack(symbol="AAPL", snippets=[_snippet(kind="moat")])
    raw = (
        '{"brand_strength":1.5,"network_effects":1.0,"switching_costs":1.5,'
        '"regulatory_ip":1.0,"moat_durability_years":10,'
        '"recommended_max_allocation_conservative":6,'
        '"reasoning":"switching costs = 10-K Item 1","macro_factors":[]}'
    )
    cfg = SimpleNamespace(provider="claude", model="claude-sonnet-4-6", api_key="x", enabled=True)
    with (
        patch.object(MoatAnalyzer, "_call_api", return_value=raw),
        patch.object(
            MoatAnalyzer, "_get_cache", return_value=MagicMock(get=lambda *_a, **_k: None)
        ),
    ):
        out = MoatAnalyzer().analyze_with_ai(
            quant, "AAPL", {"longName": "Apple"}, cfg, filing_pack=pack
        )
    assert (
        out.gross_margin_level,
        out.gross_margin_stability,
        out.roic_sustained,
        out.revenue_defensiveness,
        out.fcf_conversion,
        out.fcf_margin,
        out.quant_total,
    ) == snapshot


def test_ai_parse_fail_does_not_change_fund_scores():
    from analysis.ai_analyzer import AIAnalyzer
    from tests.test_strategy import _fund, _tech

    fund = _fund(score=77.0)
    fund.filing_evidence = empty_pack("TEST", "fetch_failed")
    fund.moat_detail = MoatDetail(quant_total=8.5)
    tech = _tech()
    cfg = SimpleNamespace(provider="claude", model="claude-sonnet-4-6", api_key="x", enabled=True)
    before_adj = fund.adjusted_score
    before_q = fund.moat_detail.quant_total
    with patch.object(AIAnalyzer, "_call_api", return_value="this is not json {{{"):
        decision = AIAnalyzer(cfg).analyze(fund, tech)
    assert fund.adjusted_score == before_adj
    assert fund.moat_detail.quant_total == before_q
    # Fallback is rule-based; overlay still sees the empty pack on an AI-enabled
    # fund. Rule-based has no invented catalysts. Score field is the engine's.
    assert (
        decision.fundamental_score == before_adj or decision.fundamental_score == fund.total_score
    )


def test_ai_off_full_analysis_skips_pack_policy():
    from analysis.strategy import full_analysis
    from tests.test_strategy import _fund, _tech

    fund = _fund(score=70.0)
    fund.filing_evidence = None
    tech = _tech()
    cfg = SimpleNamespace(enabled=False, enrich_only=False, provider="claude", model="x")
    with (
        patch("analysis.fundamental.FundamentalAnalyzer.analyze", return_value=fund),
        patch("analysis.technical.TechnicalAnalyzer.analyze", return_value=tech),
        patch("config.is_crypto", return_value=False),
    ):
        _f, _t, decision = full_analysis("TEST", ai_config=cfg)
    assert getattr(decision, "catalysts", []) == []
    assert _f.filing_evidence is None
    assert "ninguno citado" not in (decision.ai_reasoning or "")


def test_filing_panel_hidden_when_ai_off():
    pack = FilingEvidencePack(symbol="AAPL", snippets=[_snippet()])
    state = filing_panel_state(ai_on=False, pack=pack, catalysts=[])
    assert state["show_expander"] is False
    assert state["show_empty_caption"] is False


def test_filing_panel_empty_caption_when_ai_on_without_catalysts():
    state = filing_panel_state(ai_on=True, pack=empty_pack("AAPL", "no_cik"), catalysts=[])
    assert state["show_empty_caption"] is True
    assert state["empty_caption"] == "Sin catalizadores citados"
    assert state["show_expander"] is False


def test_none_pack_prompt_unchanged():
    from analysis.prompts import equity_decision_prompt
    from tests.test_prompts import _equity_fund, _tech

    a = equity_decision_prompt(_equity_fund(), _tech())
    b = equity_decision_prompt(_equity_fund(), _tech(), filing_pack=None)
    assert a == b
    assert "EVIDENCE PACK" not in a


def test_empty_pack_prompt_forbids_invention():
    from analysis.prompts import equity_decision_prompt
    from tests.test_prompts import _equity_fund, _tech

    prompt = equity_decision_prompt(
        _equity_fund(), _tech(), filing_pack=empty_pack("AAPL", "no_cik")
    )
    assert "NO HAY FILING CITABLE" in prompt
    assert "catalysts DEBE ser []" in prompt
