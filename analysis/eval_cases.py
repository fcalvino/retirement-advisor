"""
Golden cases for the AI eval harness (Gran Salto — Fase 2A).

Each case is a realistic input scenario (a ``FundamentalResult`` +
``TechnicalResult``) plus the *expectations* a good AI decision must satisfy, and
a ``replay_response`` — a recorded raw JSON the model "would" return. The replay
response lets the harness run deterministically in CI with no API key or cost;
the same cases can be re-run live against a real provider.

The fixtures here are intentionally *good* responses (they should pass the
checks). Deliberately broken responses live in the tests, where they verify that
each check actually catches its failure mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional, Set

from analysis.fundamental import FundamentalResult
from analysis.technical import TechnicalResult

# --------------------------------------------------------------------------- #
#  Compact stub builders (kept self-contained — no network)                   #
# --------------------------------------------------------------------------- #

def _fund(
    symbol: str,
    *,
    company: str,
    sector: str,
    total_score: float,
    current_price: float,
    roe: float,
    net_margin: float,
    debt_equity: float,
    pe_ratio: float,
    margin_of_safety_pct: float,
    moat: str = "Narrow",
    is_crypto: bool = False,
    adjusted_score: Optional[float] = None,
) -> FundamentalResult:
    r = FundamentalResult(symbol=symbol)
    r.company_name = company
    r.sector = sector
    r.industry = sector
    r.current_price = current_price
    r.market_cap = 5e11
    r.total_score = total_score
    r.adjusted_score = adjusted_score if adjusted_score is not None else total_score
    r.roe = roe
    r.roic = roe * 0.8
    r.net_margin = net_margin
    r.gross_margin = max(net_margin * 2, 30.0)
    r.debt_equity = debt_equity
    r.current_ratio = 1.4
    r.interest_coverage = 12.0
    r.pe_ratio = pe_ratio
    r.peg_ratio = 1.8
    r.ev_ebitda = pe_ratio * 0.8
    r.pb_ratio = 6.0
    r.fcf_yield = 4.0
    r.dividend_yield = 1.2
    r.payout_ratio = 25.0
    r.margin_of_safety_pct = margin_of_safety_pct
    r.graham_value = current_price * (1 + margin_of_safety_pct / 100.0)
    r.revenue_cagr_5y = 9.0
    r.eps_cagr_5y = 11.0
    r.moat_classification = moat
    r.moat_score = {"Wide": 16.0, "Narrow": 11.0, "Minimal": 6.0, "None": 2.0}.get(moat, 8.0)
    r.is_crypto = is_crypto
    return r


def _tech(symbol: str, *, signal: str, rsi: float, price: float, vs_low: float = 30.0) -> TechnicalResult:
    t = TechnicalResult(symbol=symbol)
    t.signal = signal
    t.signal_strength = {"BULLISH": 55, "NEUTRAL": 0, "BEARISH": -55}.get(signal, 0)
    t.current_price = price
    t.above_sma50 = signal == "BULLISH"
    t.above_sma200 = signal != "BEARISH"
    t.sma200_slope_pct = 1.2 if signal == "BULLISH" else -0.5
    t.rsi_weekly = rsi
    t.macd_bullish = signal == "BULLISH"
    t.adx = 26.0
    t.atr_pct = 1.5
    t.price_vs_52w_high_pct = -6.0
    t.price_vs_52w_low_pct = vs_low
    return t


# --------------------------------------------------------------------------- #
#  Case model                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class GoldenCase:
    case_id: str
    description: str
    fund: FundamentalResult
    tech: TechnicalResult
    expected_actions: Set[str]
    replay_response: str
    forbidden_actions: Set[str] = field(default_factory=set)
    must_have_risks: bool = True
    expect_macro_about: Optional[str] = None  # substring expected somewhere in macro_factors text
    notes: str = ""


def _resp(
    action: str,
    confidence: str,
    reasoning: str,
    rationale: List[str],
    risks: List[str],
    macro_factors: Optional[List[dict]] = None,
    alloc: Optional[float] = None,
) -> str:
    payload = {
        "action": action,
        "confidence": confidence,
        "reasoning": reasoning,
        "rationale": rationale,
        "risks": risks,
        "macro_factors": macro_factors or [],
    }
    if alloc is not None:
        payload["recommended_max_allocation_conservative"] = alloc
    return json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------------------- #
#  The golden set                                                             #
# --------------------------------------------------------------------------- #

def golden_cases() -> List[GoldenCase]:
    cases: List[GoldenCase] = []

    # 1 — Quality compounder, attractive: should be a BUY that still names risks.
    f = _fund("MSFT", company="Microsoft", sector="Technology", total_score=78.0,
              current_price=400.0, roe=38.0, net_margin=36.0, debt_equity=0.5,
              pe_ratio=30.0, margin_of_safety_pct=12.0, moat="Wide")
    t = _tech("MSFT", signal="BULLISH", rsi=58.0, price=400.0)
    cases.append(GoldenCase(
        case_id="quality_compounder_buy",
        description="Compounder de calidad con margen de seguridad — BUY con riesgos explícitos.",
        fund=f, tech=t,
        expected_actions={"BUY", "STRONG BUY"},
        forbidden_actions={"SELL", "REDUCE"},
        replay_response=_resp(
            action="BUY", confidence="HIGH",
            reasoning=("Microsoft combina un ROE de 38.0% y un margen neto de 36.0% con un moat "
                       "Wide y deuda baja (D/E 0.5), a un P/E de 30.0 con margen de seguridad de "
                       "12.0%. La señal técnica es BULLISH con RSI 58.0, sin sobrecompra."),
            rationale=["ROE 38.0% y margen neto 36.0% sostienen el compounding",
                       "Moat Wide con D/E 0.5 reduce el riesgo de capital"],
            risks=["P/E 30.0 deja poco margen ante una desaceleración del crecimiento",
                   "Concentración tecnológica si ya hay exposición al sector"],
            alloc=8.0,
        ),
    ))

    # 2 — High leverage, weak valuation: caution, must flag risks, modest/zero alloc.
    f = _fund("XYZ", company="LeveredCo", sector="Industrials", total_score=38.0,
              current_price=50.0, roe=9.0, net_margin=4.0, debt_equity=2.6,
              pe_ratio=11.0, margin_of_safety_pct=-8.0, moat="Minimal")
    t = _tech("XYZ", signal="BEARISH", rsi=44.0, price=50.0)
    cases.append(GoldenCase(
        case_id="high_leverage_caution",
        description="Apalancamiento alto (D/E 2.6) y calidad débil — REDUCE/SELL con riesgos.",
        fund=f, tech=t,
        expected_actions={"REDUCE", "SELL", "HOLD"},
        forbidden_actions={"STRONG BUY", "BUY"},
        replay_response=_resp(
            action="SELL", confidence="HIGH",
            reasoning=("LeveredCo muestra D/E de 2.6, muy por encima del umbral conservador, con "
                       "ROE de 9.0% y margen neto de 4.0%. La señal técnica es BEARISH. El riesgo "
                       "de capital domina cualquier descuento de valuación (P/E 11.0)."),
            rationale=["D/E 2.6 implica fragilidad financiera para un horizonte de retiro",
                       "Señal técnica BEARISH confirma el deterioro"],
            risks=["Alto apalancamiento amplifica pérdidas en una recesión",
                   "Margen neto 4.0% deja escaso colchón ante shocks de costos"],
            alloc=0.0,
        ),
    ))

    # 3 — Strong fundamentals but overbought: hold/accumulate slowly, caution on entry.
    f = _fund("NVDA", company="Nvidia", sector="Technology", total_score=74.0,
              current_price=120.0, roe=45.0, net_margin=50.0, debt_equity=0.4,
              pe_ratio=55.0, margin_of_safety_pct=-20.0, moat="Wide")
    t = _tech("NVDA", signal="BULLISH", rsi=82.0, price=120.0, vs_low=180.0)
    cases.append(GoldenCase(
        case_id="overbought_wait",
        description="Calidad alta pero sobrecompra (RSI 82) y sin margen — HOLD/cautela en la entrada.",
        fund=f, tech=t,
        expected_actions={"HOLD", "REDUCE"},
        forbidden_actions={"STRONG BUY"},
        replay_response=_resp(
            action="HOLD", confidence="MEDIUM",
            reasoning=("Nvidia tiene fundamentos excelentes (ROE 45.0%, margen neto 50.0%, moat "
                       "Wide) pero cotiza a P/E 55.0 con margen de seguridad de -20.0% y RSI "
                       "semanal de 82.0, en zona de sobrecompra. Conviene esperar un retroceso."),
            rationale=["Calidad de negocio intacta (ROE 45.0%, moat Wide)",
                       "Valuación exigente: P/E 55.0 y margen de seguridad -20.0%"],
            risks=["RSI 82.0 indica sobrecompra; entrada ahora corre riesgo de drawdown",
                   "Múltiplo alto castiga fuerte si el crecimiento decepciona"],
            alloc=4.0,
        ),
    ))

    # 4 — Crypto: conservative cap, must flag volatility risks.
    f = _fund("BTC-USD", company="Bitcoin", sector="Crypto / Digital Asset", total_score=0.0,
              current_price=100000.0, roe=0.0, net_margin=0.0, debt_equity=0.0,
              pe_ratio=0.0, margin_of_safety_pct=0.0, moat="Narrow",
              is_crypto=True, adjusted_score=55.0)
    t = _tech("BTC-USD", signal="NEUTRAL", rsi=60.0, price=100000.0)
    cases.append(GoldenCase(
        case_id="crypto_conservative_cap",
        description="Cripto para perfil conservador — tope de asignación bajo y riesgos de volatilidad.",
        fund=f, tech=t,
        expected_actions={"HOLD", "REDUCE", "BUY"},
        replay_response=_resp(
            action="HOLD", confidence="LOW",
            reasoning=("Bitcoin tiene un score ajustado de 55.0. Para un perfil de retiro "
                       "conservador su rol es satélite: volatilidad anualizada elevada y drawdowns "
                       "históricos profundos exigen un tope de asignación muy bajo."),
            rationale=["Activo satélite, no núcleo, para un horizonte de retiro",
                       "Score ajustado 55.0 no justifica una posición grande"],
            risks=["Volatilidad y drawdowns históricos superiores al 70%",
                   "Sin flujo de caja ni valor intrínseco que ancle el precio"],
            alloc=2.0,
        ),
    ))

    # 5 — Argentine ADR: macro_factors should reference country/FX risk.
    f = _fund("YPF", company="YPF S.A.", sector="Energy", total_score=52.0,
              current_price=25.0, roe=14.0, net_margin=8.0, debt_equity=1.1,
              pe_ratio=7.0, margin_of_safety_pct=18.0, moat="Narrow")
    t = _tech("YPF", signal="NEUTRAL", rsi=55.0, price=25.0)
    cases.append(GoldenCase(
        case_id="argentina_adr_macro",
        description="ADR argentino — el dictamen debe anclar el riesgo país/FX en macro_factors.",
        fund=f, tech=t,
        expected_actions={"HOLD", "BUY", "REDUCE"},
        expect_macro_about="argentin",
        replay_response=_resp(
            action="HOLD", confidence="MEDIUM",
            reasoning=("YPF cotiza a P/E 7.0 con margen de seguridad de 18.0% y ROE de 14.0%, "
                       "pero su perfil está dominado por el riesgo argentino: brecha cambiaria, "
                       "controles de capital y volatilidad regulatoria que pesan sobre el ADR."),
            rationale=["Valuación barata (P/E 7.0) con margen de seguridad 18.0%",
                       "El riesgo país condiciona la repatriación de dividendos"],
            risks=["Riesgo regulatorio y de controles de cambio en Argentina",
                   "Volatilidad del ADR por brecha ARS/USD"],
            macro_factors=[{
                "factor": "Riesgo país Argentina",
                "why_relevant": "YPF es un ADR argentino del sector energía expuesto a controles FX",
                "impact": "Comprime el múltiplo y agrega volatilidad sobre el P/E 7.0",
                "effect_on_allocation_or_conviction": "Mantiene la convicción en MEDIUM y limita el tamaño",
            }],
            alloc=5.0,
        ),
    ))

    # 6 — Middling quality, fairly valued: a clean HOLD.
    f = _fund("KO", company="Coca-Cola", sector="Consumer Staples", total_score=58.0,
              current_price=60.0, roe=22.0, net_margin=23.0, debt_equity=1.6,
              pe_ratio=24.0, margin_of_safety_pct=-2.0, moat="Wide")
    t = _tech("KO", signal="NEUTRAL", rsi=52.0, price=60.0)
    cases.append(GoldenCase(
        case_id="fair_value_hold",
        description="Calidad media, valuación justa — HOLD limpio con riesgos suaves.",
        fund=f, tech=t,
        expected_actions={"HOLD", "BUY"},
        forbidden_actions={"SELL"},
        replay_response=_resp(
            action="HOLD", confidence="MEDIUM",
            reasoning=("Coca-Cola tiene un moat Wide y márgenes sólidos (ROE 22.0%, margen neto "
                       "23.0%) pero cotiza a P/E 24.0 con margen de seguridad de -2.0%. A precio "
                       "justo, mantener es lo razonable para un perfil de ingresos."),
            rationale=["Moat Wide y dividendos defienden el rol de ingresos",
                       "Valuación justa (P/E 24.0) no ofrece descuento claro"],
            risks=["D/E 1.6 algo elevado para staples",
                   "Crecimiento bajo limita el upside de capital"],
            alloc=6.0,
        ),
    ))

    return cases
