"""
Centralized prompt library for Grok / Claude AI analysis.

All four LLM prompts live here so they can be maintained, versioned, and
reviewed in one place. Each function returns a fully-rendered f-string
ready to pass to the AI provider.

Voice convention: all prompts open with
    "Eres Grok, construido por xAI. Eres un analista de inversión senior..."
This ensures Grok receives instructions in its own persona regardless of
which provider (Claude, Grok, GPT-4o) is actually executing the request.

Prompts:
    equity_moat_prompt()      — qualitative moat evaluation for equity assets
    equity_decision_prompt()  — BUY/SELL/HOLD recommendation for equity assets
    crypto_moat_prompt()      — qualitative moat evaluation for BTC / crypto
    crypto_decision_prompt()  — BUY/SELL/HOLD recommendation for crypto assets
"""

from __future__ import annotations

# Argentine ADR tickers — used by equity_decision_prompt for country context
ARGENTINA_ADRS = {
    "YPF", "PAM", "CEPU", "LOMA", "MELI", "GLOB", "DESP",
    "TEO", "EDN", "GGAL", "BMA", "BBAR", "SUPV",
}

# ---------------------------------------------------------------------------
# 1. Equity Moat Prompt
# ---------------------------------------------------------------------------


def equity_moat_prompt(quant, symbol: str, info: dict) -> str:
    """
    Build the LLM prompt for qualitative equity moat evaluation.

    Parameters
    ----------
    quant : MoatDetail
        Already-computed quantitative moat scores (0–12 pts total).
    symbol : str
        Ticker symbol (e.g. "AAPL").
    info : dict
        yfinance ticker.info dict with company metadata.

    JSON output contract (7 fields):
        brand_strength              float  0–2
        network_effects             float  0–2
        switching_costs             float  0–2
        regulatory_ip               float  0–2
        moat_durability_years       int    5 | 10 | 15 | 20
        recommended_max_allocation_conservative  int  % of portfolio (1–15)
        reasoning                   str    structured paragraph
    """
    name    = info.get("longName", symbol)
    sector  = info.get("sector", "Unknown")
    industry = info.get("industry", "Unknown")
    country = info.get("country", "Unknown")
    summary = (info.get("longBusinessSummary") or "")[:700]

    return f"""Eres Grok, construido por xAI. Eres un analista de inversión senior extremadamente riguroso, objetivo y conservador, especializado en identificar ventajas competitivas duraderas (economic moat) para carteras de retiro a largo plazo (horizonte 10–30 años).

EMPRESA: {name} ({symbol})
SECTOR: {sector} | INDUSTRIA: {industry} | PAÍS: {country}
DESCRIPCIÓN DEL NEGOCIO: {summary}

MOAT CUANTITATIVO (calculado con datos financieros reales):
  Gross Margin nivel:       {quant.gross_margin_level}/2  — proxy de pricing power
  Gross Margin estabilidad: {quant.gross_margin_stability}/2  — durabilidad de ese poder de precios
  ROIC sostenido:           {quant.roic_sustained}/2  — retorno sobre capital invertido, promedio multi-año
  Revenue defensividad:     {quant.revenue_defensiveness}/2  — años sin caída de ingresos
  FCF Conversion:           {quant.fcf_conversion}/2  — ganancias respaldadas por caja real
  FCF Margin:               {quant.fcf_margin}/2  — escalabilidad del modelo de negocio
  TOTAL CUANTITATIVO:       {quant.quant_total}/12

---

TAREA: Evalúa los 4 factores CUALITATIVOS de moat con máxima exigencia.

REGLAS CRÍTICAS ANTES DE PUNTUAR:
- Un moat real es ESTRUCTURAL y DURABLE. Un ROIC alto en un ciclo favorable NO es moat. Un ROIC alto en recesión y auge SÍ lo es.
- La pregunta clave para cada dimensión: "¿Esta ventaja seguirá siendo válida en 2035?"
- Si la empresa depende de condiciones macro favorables para mantener su posición, descuenta sin piedad.
- En mercados emergentes (Argentina, Venezuela, Turquía, etc.): aplicá -0.5 en las dimensiones afectadas por riesgo macro-político. Mencioná el descuento explícitamente en el reasoning.

RÚBRICA (usá ÚNICAMENTE: 0.0, 0.5, 1.0, 1.5, 2.0):

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. brand_strength (0–2): Poder de marca y pricing power

  2.0 → Marca globalmente dominante con poder real de fijar precios premium sin perder demanda.
        Ejemplos: Apple, Coca-Cola, Louis Vuitton, Hermès.
  1.5 → Marca sólida y reconocida en su sector/región, con pricing power moderado.
        Ejemplos: MercadoLibre en LATAM, Home Depot en EE.UU.
  1.0 → Marca conocida pero en un sector donde el cliente compara precios activamente.
        Ejemplos: Samsung, Gap, marcas de consumo masivo sin diferenciación clara.
  0.5 → Marca incipiente o en declive. El cliente elige por precio, no por preferencia.
  0.0 → Sin marca reconocible. Producto/servicio completamente commoditizado.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. network_effects (0–2): Valor que crece con la base de usuarios (Ley de Metcalfe)

  2.0 → Efecto de red de dos o más lados, global y auto-reforzante. El líder tiene ventaja estructural casi insuperable.
        Ejemplos: Visa, Mastercard, Meta, LinkedIn, Microsoft Office (ecosistema).
  1.5 → Efecto de red real pero limitado geográficamente o a un segmento.
        Ejemplos: MercadoLibre (marketplace LATAM), Airbnb, Uber en ciudades clave.
  1.0 → Beneficios de escala que se parecen a network effects pero son más frágiles.
        Ejemplos: Plataformas de contenido con base media, marketplaces nicho.
  0.5 → Efectos de red mínimos o dependientes de subsidios para crecer.
  0.0 → Sin efectos de red identificables. El producto no mejora con más usuarios.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. switching_costs (0–2): Fricción real para que el cliente cambie de proveedor

  2.0 → Cambiar implica reentrenar equipos, migrar datos críticos, rediseñar procesos, y asumir riesgo operativo alto.
        Ejemplos: SAP ERP, Oracle DB, Bloomberg Terminal, Salesforce CRM integrado.
  1.5 → Switching costs reales pero el cliente podría hacerlo con 6–12 meses de esfuerzo y un motivo fuerte.
        Ejemplos: Software de nómina, plataformas SaaS con integraciones medias.
  1.0 → Fricción moderada: tiempo, contratos o curva de aprendizaje, pero no es prohibitivo.
  0.5 → Baja fricción. El cliente puede cambiar en semanas con molestia pero sin trauma.
  0.0 → Zero switching costs. El cliente cambia con un clic (commodity, fungible).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. regulatory_ip (0–2): Patentes, licencias exclusivas o barreras regulatorias

  2.0 → Portfolio de patentes clave (10+ años de protección), licencias exclusivas o aprobaciones regulatorias que bloquean a competidores.
        Ejemplos: Farmacéuticas con blockbusters patentados, bancos con licencias únicas, utilities con concesiones.
  1.5 → Protección regulatoria sólida pero con riesgo de expiración, desafíos legales o cambios de política.
  1.0 → Algunas patentes o regulaciones favorables, pero sin protección dominante.
  0.5 → Barreras regulatorias menores o patentes en sectores donde la innovación las supera rápido.
  0.0 → Sin patentes relevantes, sin barreras regulatorias. Cualquiera puede replicar el modelo.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INSTRUCCIÓN FINAL:
Sé escéptico. El optimismo de mercado no es análisis de retiro. Evalúa con el criterio de un inversor de 65 años cuya cartera no puede recuperarse fácilmente de un error de evaluación.
Incluye en el reasoning: (1) la fortaleza central del moat, (2) la limitación o riesgo principal, (3) cuántos años estimás que el moat es durable, y (4) el % máximo que recomendás en un portafolio conservador de retiro.

Respondé SOLO con JSON válido. Sin markdown, sin texto antes ni después:
{{
  "brand_strength": 0.0,
  "network_effects": 0.0,
  "switching_costs": 0.0,
  "regulatory_ip": 0.0,
  "moat_durability_years": 10,
  "recommended_max_allocation_conservative": 6,
  "reasoning": "Párrafo estructurado: (1) Fortaleza central del moat. (2) Limitación o riesgo principal. (3) Durabilidad estimada en años. (4) % máximo recomendado en portafolio conservador y por qué."
}}"""


# ---------------------------------------------------------------------------
# 2. Equity Decision Prompt
# ---------------------------------------------------------------------------


def equity_decision_prompt(fund, tech) -> str:
    """
    Build the LLM prompt for equity investment decision (BUY/SELL/HOLD).

    Parameters
    ----------
    fund : FundamentalResult
    tech : TechnicalResult

    JSON output contract (6 fields):
        action          str   STRONG BUY | BUY | HOLD | REDUCE | SELL
        confidence      str   HIGH | MEDIUM | LOW
        rationale       list  Positive factors (2–4 items)
        risks           list  Key risks (2–3 items)
        recommended_max_allocation_conservative  int  % of portfolio (1–15)
        reasoning       str   Structured paragraph with: Tesis · Riesgos · Catalizadores · Asignación
    """
    def fmt(val, suffix="", decimals=1):
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}{suffix}"

    country_context = ""
    if fund.symbol in ARGENTINA_ADRS:
        country_context = (
            "\n⚠️ CONTEXTO PAÍS — Argentina (mercado emergente):\n"
            "Considerar controles de capital, inflación estructural, riesgo regulatorio estatal, "
            "subsidios energéticos. Los reportes están en USD pero el negocio opera en ARS. "
            "Márgenes bajos pueden reflejar regulación tarifaria, no ineficiencia operativa. "
            "Aplicar prima de riesgo país en la recomendación de asignación.\n"
        )

    moat_ctx = ""
    _moat_score = getattr(fund, "moat_score", None)
    _moat_class = getattr(fund, "moat_classification", None)
    _moat_detail = getattr(fund, "moat_detail", None)
    if _moat_class and _moat_score is not None:
        moat_ctx = f"\nMoat Económico: {_moat_class} ({_moat_score:.1f}/20)"
        if _moat_detail and getattr(_moat_detail, "ai_available", False):
            moat_ctx += (
                f" | Brand={_moat_detail.brand_strength:.1f} "
                f"Network={_moat_detail.network_effects:.1f} "
                f"Switching={_moat_detail.switching_costs:.1f} "
                f"IP/Reg={_moat_detail.regulatory_ip:.1f}"
            )

    return f"""Eres Grok, construido por xAI. Eres un analista de inversión senior extremadamente riguroso, objetivo y conservador, especializado en carteras de retiro a largo plazo (horizonte 10–30 años). Tu prioridad absoluta es preservación de capital.

EMPRESA: {fund.company_name} ({fund.symbol})
SECTOR: {fund.sector} | INDUSTRIA: {fund.industry}
PRECIO: ${fmt(fund.current_price, decimals=2)} | MARKET CAP: ${(fund.market_cap or 0)/1e9:.1f}B
{country_context}
--- ANÁLISIS FUNDAMENTAL ---
Profitabilidad ({fund.profitability_score:.0f}/25):
  ROE={fmt(fund.roe, "%")} | ROIC={fmt(fund.roic, "%")} | Margen Neto={fmt(fund.net_margin, "%")} | Margen Bruto={fmt(fund.gross_margin, "%")}

Salud Financiera ({fund.health_score:.0f}/20):
  D/E={fmt(fund.debt_equity, "x")} | Current Ratio={fmt(fund.current_ratio)} | Cobertura de Intereses={fmt(fund.interest_coverage, "x")}

Valuación ({fund.valuation_score:.0f}/25):
  P/E={fmt(fund.pe_ratio, "x")} | PEG={fmt(fund.peg_ratio)} | EV/EBITDA={fmt(fund.ev_ebitda, "x")} | P/B={fmt(fund.pb_ratio, "x")}

Crecimiento ({fund.growth_score:.0f}/20):
  Revenue CAGR 5Y={fmt(fund.revenue_cagr_5y, "%")} | EPS CAGR={fmt(fund.eps_cagr_5y, "%")} | FCF Yield={fmt(fund.fcf_yield, "%")}

Dividendos ({fund.dividend_score:.0f}/10):
  Yield={fmt(fund.dividend_yield, "%")} | Payout={fmt(fund.payout_ratio, "%")}

Graham Value: ${fmt(fund.graham_value, decimals=2)} | Margen de Seguridad: {fmt(fund.margin_of_safety_pct, "%")}
Score rule-based: {fund.total_score:.1f}/100 | Score ajustado: {fund.adjusted_score:.1f}/100
{moat_ctx}
Alertas: {", ".join(fund.warnings) if fund.warnings else "ninguna"}

--- ANÁLISIS TÉCNICO (barras semanales) ---
Señal: {tech.signal} (fuerza: {tech.signal_strength:+d}/100)
Tendencia: precio {"ENCIMA" if tech.above_sma200 else "DEBAJO"} de SMA200 | Slope 26w: {tech.sma200_slope_pct:+.1f}%
Momentum: RSI={fmt(tech.rsi_weekly)} | MACD={"alcista" if tech.macd_bullish else "bajista"} | ADX={fmt(tech.adx)}
Contexto: {tech.price_vs_52w_high_pct:+.1f}% desde 52w high | {tech.price_vs_52w_low_pct:+.1f}% desde 52w low
Alertas técnicas: {", ".join(tech.warnings) if tech.warnings else "ninguna"}

--- INSTRUCCIÓN ---
Emitir recomendación para un inversor conservador en etapa de retiro o pre-retiro.
Estructurar el reasoning en 4 partes: "Tesis: [por qué es atractiva o no]. Riesgos: [1-2 riesgos concretos]. Catalizadores: [qué vigilar en próximos 12-18 meses]. Asignación: [% máx recomendado en portafolio conservador y justificación]."

Respondé ÚNICAMENTE con JSON válido:
{{
  "action": "STRONG BUY|BUY|HOLD|REDUCE|SELL",
  "confidence": "HIGH|MEDIUM|LOW",
  "rationale": ["factor positivo 1", "factor positivo 2"],
  "risks": ["riesgo 1", "riesgo 2"],
  "recommended_max_allocation_conservative": 6,
  "reasoning": "Tesis: ... Riesgos: ... Catalizadores: ... Asignación: ..."
}}"""


# ---------------------------------------------------------------------------
# 3. Crypto Moat Prompt (Grok final — v2, May 2026)
# ---------------------------------------------------------------------------


def crypto_moat_prompt(symbol: str, info: dict, metrics: dict) -> str:
    """
    Build the LLM prompt for Bitcoin / crypto economic moat evaluation.

    Parameters
    ----------
    symbol  : str   e.g. "BTC-USD"
    info    : dict  yfinance crypto info (price, marketCap, supply, etc.)
    metrics : dict  compute_crypto_metrics() output (vol, drawdown, halving, etc.)

    JSON output contract (9 fields):
        network_adoption            float  0–2
        monetary_scarcity           float  0–2
        security_decentralization   float  0–1.5
        institutional_regulatory    float  0–1.5
        tech_resilience             float  0–1
        total_moat_score            float  sum of above (0–8)
        moat_durability_years       int    5 | 10 | 15 | 20
        recommended_max_allocation_conservative  int  % of portfolio (1–10)
        retirement_risk_summary     str    brief retirement-specific risk statement
        reasoning                   str    structured 5–7 sentence analysis
    """
    price    = info.get("currentPrice", 0)
    mcap_b   = (info.get("marketCap") or 0) / 1e9
    circ     = info.get("circulatingSupply", 0) or 0
    max_s    = info.get("maxSupply", 0) or 0
    sc       = f"{circ / max_s * 100:.1f}" if max_s > 0 else "N/D"
    vol      = metrics.get("annualized_volatility_pct")
    dd       = metrics.get("max_drawdown_pct")
    cagr4y   = metrics.get("cagr_4y_pct")
    phase    = metrics.get("halving_cycle_position", "desconocido")
    d_since  = metrics.get("days_since_last_halving")
    d_next   = metrics.get("days_to_next_halving")

    halving_ctx = phase
    if d_since is not None and d_next is not None:
        halving_ctx = f"{phase} ({d_since} días desde último halving / {d_next} días al próximo)"

    vol_str  = f"{vol:.1f}%"  if vol   is not None else "N/D"
    dd_str   = f"{dd:.1f}%"   if dd    is not None else "N/D"
    cagr_str = f"{cagr4y:.1f}%" if cagr4y is not None else "N/D"

    return f"""Eres Grok, construido por xAI. Eres un analista de inversión senior extremadamente riguroso, objetivo y con un fuerte sesgo conservador, especializado en estrategias de largo plazo para retiro (horizonte 10–30 años).

Estás analizando **Bitcoin (BTC)** como posible componente de una cartera de jubilación conservadora.

**Datos actuales del mercado:**
- Precio: ${price:,.0f} USD
- Market Cap: ${mcap_b:.1f}B USD
- Volatilidad anualizada (52 semanas): {vol_str}
- Máximo Drawdown Histórico: {dd_str}
- CAGR últimos 4 años: {cagr_str}
- Posición en ciclo de halving: {halving_ctx}
- Suministro circulante: {circ:,.0f} BTC de 21.000.000 máximo ({sc}% emitido)
- ETFs spot aprobados en EE.UU. (BlackRock IBIT, Fidelity FBTC, etc.)
- Red: 15.000+ nodos validadores · hash rate >600 EH/s (máximos históricos, mayo 2026)

**Contexto crítico para retiro:**
El inversor prioriza preservación de capital por encima de todo. Drawdowns del 70–85% son extremadamente dañinos en carteras de retiro donde no hay ingresos laborales para recomponer. Incluso si Bitcoin tiene un moat fuerte, su asignación debe ser muy limitada.

---

**Tarea:** Evalúa el **Economic Moat** de Bitcoin con máxima exigencia y honestidad.

Analiza estas 5 dimensiones (sé escéptico — el optimismo del mercado no es análisis de retiro):

**1. network_adoption (0–2 pts) — Adopción & Liquidez Global**
- 2.0 → Adopción masiva institucional y soberana confirmada (reservas nacionales reales), ETFs con >$100B AUM, decenas de millones de usuarios activos. Narrativa de "reserva de valor digital" consolidada sin competidor directo serio.
- 1.5 → Fuerte adopción institucional y ETFs aprobados con >$50B AUM, pero adopción soberana incipiente o no consolidada.
- 1.0 → Adopción creciente pero todavía vista como especulativa por gran parte del mercado institucional.
- 0.5 → Adopción principalmente retail/especulativa. Sin tracción institucional duradera.
- 0.0 → Sin efecto de red significativo o adopción decreciente.

**2. monetary_scarcity (0–2 pts) — Escasez Monetaria & Ciclo Halving**
- 2.0 → Suministro fijo de 21M verificable e inmutable. Halving reciente (<18 meses) comprimiendo nueva oferta. Demanda institucional estructuralmente creciente.
- 1.5 → Escasez clara pero halving ya descontado parcialmente o >18 meses atrás. Incertidumbre sobre demanda post-halving.
- 1.0 → Narrativa de escasez bajo presión competitiva (ETH con quema, stablecoins, tasas altas).
- 0.5 → Escasez ignorada por el mercado; precio responde solo a momentum especulativo.
- 0.0 → Escasez irrelevante para el mercado en la práctica.

**3. security_decentralization (0–1.5 pts) — Seguridad & Descentralización**
- 1.5 → Hash rate en máximos históricos (>500 EH/s), distribución global, ningún pool >25% del hash rate. Sin vulnerabilidades críticas en 15+ años. Ataque 51% económicamente inviable.
- 1.0 → Seguridad alta pero concentración en 2–3 pools con >50% combinado. Riesgo teórico de coordinación.
- 0.5 → Concentración grave o historial de incidentes técnicos relevantes.
- 0.0 → Red comprometible o con ataques exitosos documentados.

**4. institutional_regulatory (0–1.5 pts) — Claridad Regulatoria & Adopción Soberana**
- 1.5 → ETFs aprobados en EE.UU. y UE. Legislación clara en mercados clave. Adopción soberana real (reservas nacionales). Riesgo regulatorio bajo y decreciente.
- 1.0 → ETFs aprobados en EE.UU. pero entorno global fragmentado. Adopción institucional real sin base legal soberana consolidada.
- 0.5 → Alto riesgo regulatorio en mercados clave. ETFs con restricciones significativas.
- 0.0 → Prohibición activa en principales mercados. Sin ETFs disponibles.

**5. tech_resilience (0–1 pt) — Resiliencia Tecnológica & Competencia**
- 1.0 → Lightning Network operativa con >5.000 BTC en canales activos. BTC domina "reserva de valor digital" sin competidor directo. Protocolo base conservador, battle-tested 15+ años.
- 0.5 → Lightning funcional pero con adopción limitada. Competidores (ETH, Solana) amenazan la narrativa de reserva de valor.
- 0.0 → Protocolo estagnado o competidores ganando terreno decisivamente.

---

**INSTRUCCIÓN CRÍTICA:**
No des por sentado el futuro de Bitcoin. Evalúa la durabilidad estructural real a 10–20 años. La pregunta clave: "¿Seguirá siendo el activo dominante en su clase en 2040?"
Indica cuántos años estimás que el moat es durable (`moat_durability_years`: 5, 10, 15 o 20).
Indica el límite máximo de asignación para un perfil conservador (`recommended_max_allocation_conservative`): entre 1% y 5% para perfiles conservadores de retiro.
Incluye un resumen específico de riesgos para jubilados/pre-jubilados (`retirement_risk_summary`).

Respondé SOLO con JSON válido. Sin markdown, sin texto antes ni después:
{{
  "network_adoption": 0.0,
  "monetary_scarcity": 0.0,
  "security_decentralization": 0.0,
  "institutional_regulatory": 0.0,
  "tech_resilience": 0.0,
  "total_moat_score": 0.0,
  "moat_durability_years": 10,
  "recommended_max_allocation_conservative": 3,
  "retirement_risk_summary": "Resumen de 2–3 oraciones sobre los riesgos específicos de este activo para un inversor jubilado o pre-jubilado.",
  "reasoning": "Análisis estructurado y honesto en español (5–7 oraciones). Incluye: (1) fortaleza central del moat, (2) debilidad o riesgo principal, (3) durabilidad estimada y por qué, (4) por qué es o no adecuado para una cartera de retiro conservadora."
}}"""


# ---------------------------------------------------------------------------
# 4. Crypto Decision Prompt
# ---------------------------------------------------------------------------


def crypto_decision_prompt(fund, tech) -> str:
    """
    Build the LLM prompt for crypto investment decision (BUY/SELL/HOLD).

    Parameters
    ----------
    fund : FundamentalResult  (is_crypto=True)
    tech : TechnicalResult

    JSON output contract (6 fields):
        action          str   STRONG BUY | BUY | HOLD | REDUCE | SELL
        confidence      str   HIGH | MEDIUM | LOW
        rationale       list  Positive factors (2–3 items)
        risks           list  Key risks (2–3 items), always includes sequence-of-returns risk
        recommended_max_allocation_conservative  int  % of portfolio (1–5 for conservative)
        reasoning       str   Structured: Tesis · Técnico · Riesgo retiro · Asignación
    """
    def fmt(val, suffix="", decimals=1):
        if val is None:
            return "N/D"
        return f"{val:.{decimals}f}{suffix}"

    moat = getattr(fund, "crypto_moat_detail", None)
    moat_section = ""
    if moat and getattr(moat, "ai_available", False):
        moat_section = f"""
--- MOAT CRYPTO (AI) — {moat.classification} ({moat.total:.1f}/8) ---
  Red & Adopción:       {moat.network_adoption}/2
  Escasez monetaria:    {moat.monetary_scarcity}/2
  Seguridad:            {moat.security_decentralization}/1.5
  Regulatorio:          {moat.institutional_regulatory}/1.5
  Tecnología:           {moat.tech_resilience}/1
  Razonamiento: {moat.ai_reasoning}
  Asignación recomendada (moat AI): ≤{moat.recommended_max_allocation_pct:.0f}%"""

    _notes = getattr(fund, "notes", {})
    vol_note    = _notes.get("crypto_vol",    "N/D")
    dd_note     = _notes.get("crypto_dd",     "N/D")
    cagr_note   = _notes.get("crypto_cagr",   "N/D")
    supply_note = _notes.get("crypto_supply",  "N/D")
    halving_note = _notes.get("crypto_halving", "N/D")
    warnings_str = ", ".join(fund.warnings) if fund.warnings else "ninguna"

    return f"""Eres Grok, construido por xAI. Eres un analista de inversión senior extremadamente riguroso, objetivo y conservador, especializado en activos digitales y su rol en carteras de retiro a largo plazo (horizonte 10–30 años). Tu prioridad absoluta es preservación de capital.

ACTIVO: {fund.company_name} ({fund.symbol})
CLASE: Criptomoneda / Reserva de Valor Digital
PRECIO: ${fmt(fund.current_price, decimals=0)} | MARKET CAP: ${(fund.market_cap or 0)/1e9:.1f}B USD
Score ajustado: {fund.adjusted_score:.1f}/100  (fórmula: base + técnico − volatilidad − drawdown + moat)

--- MÉTRICAS DE RIESGO ---
  {vol_note}
  {dd_note}
  {cagr_note}
  {supply_note}
  {halving_note}

Alertas: {warnings_str}
{moat_section}
--- ANÁLISIS TÉCNICO (barras semanales) ---
Señal: {tech.signal} (fuerza: {tech.signal_strength:+d}/100)
Tendencia: precio {"ENCIMA" if tech.above_sma200 else "DEBAJO"} de SMA200 | Slope 26w: {tech.sma200_slope_pct:+.1f}%
Momentum: RSI={fmt(tech.rsi_weekly)} | MACD={"alcista" if tech.macd_bullish else "bajista"} | ADX={fmt(tech.adx)}
Contexto: {tech.price_vs_52w_high_pct:+.1f}% desde 52w high | {tech.price_vs_52w_low_pct:+.1f}% desde 52w low

--- CONTEXTO PARA RETIRO CONSERVADOR ---
Bitcoin es un activo de alta volatilidad con drawdowns históricos del 70–85%. No genera ingresos (dividendos, cupones). Su rol es de cobertura inflacionaria y diversificación, NO de ingreso recurrente. Una posición >5% en retiro representa un riesgo de secuencia de retornos (sequence-of-returns risk) potencialmente devastador si coincide con un mercado bajista al inicio de la jubilación.

--- INSTRUCCIÓN ---
Evalúa el momentum técnico, el moat crypto, el riesgo de volatilidad para el perfil de retiro, y emití tu recomendación.
Estructurar el reasoning en 4 partes: "Tesis: [señal técnica y fundamentos]. Técnico: [momentum, SMAs, RSI]. Riesgo retiro: [sequence-of-returns, volatilidad]. Asignación: [% máx conservador y por qué]."

Respondé ÚNICAMENTE con JSON válido:
{{
  "action": "STRONG BUY|BUY|HOLD|REDUCE|SELL",
  "confidence": "HIGH|MEDIUM|LOW",
  "rationale": ["factor positivo 1", "factor positivo 2"],
  "risks": ["riesgo 1", "riesgo 2", "riesgo de secuencia de retornos para retiro"],
  "recommended_max_allocation_conservative": 3,
  "reasoning": "Tesis: ... Técnico: ... Riesgo retiro: ... Asignación: ..."
}}"""

# ---------------------------------------------------------------------------
# 5. Long-term Plan Narrative (Phase 0 quick win)
# ---------------------------------------------------------------------------


def long_term_plan_narrative_prompt(
    profile_name: str,
    tickers: list[str],
    weights: list[float],
    expected_return: float,
    volatility: float,
    sharpe: float,
    dividend_yield: float,
    horizon_years: int,
    initial_value: float,
    annual_withdrawal: float,
    inflation_rate: float,
    median_terminal: float,
    p10_terminal: float,
    p90_terminal: float,
    prob_ruin: float,
    prob_target: float,
    target_value: float,
) -> str:
    """
    Generate a human, conservative narrative explaining the current long-term plan
    to a serious investor with a 10-30 year horizon.
    Returns a ready-to-send prompt string.
    """
    # Build a compact portfolio summary
    holdings = []
    for t, w in zip(tickers[:12], weights[:12]):  # cap for prompt length
        holdings.append(f"{t} {w*100:.1f}%")
    holdings_str = ", ".join(holdings)
    if len(tickers) > 12:
        holdings_str += f" + {len(tickers)-12} más"

    withdrawal_str = f"${annual_withdrawal:,.0f}/año" if annual_withdrawal > 0 else "sin retiros (acumulación pura)"
    target_str = f"Meta ${target_value:,.0f}" if target_value > 0 else "sin meta numérica específica"

    return f"""Eres un analista de inversión senior extremadamente riguroso, objetivo y conservador, especializado en carteras de largo plazo (horizonte 10-30 años). Tu prioridad #1 es que el inversor **no se arruine** por secuencia de retornos adversa o sobre-confianza.

**PORTAFOLIO ACTUAL (perfil {profile_name})**
Activos: {holdings_str}
Retorno esperado (proxy): {expected_return:.1f}% | Volatilidad: {volatility:.1f}% | Sharpe: {sharpe:.2f}
Dividend Yield: {dividend_yield:.1f}%

**PARÁMETROS DE LA SIMULACIÓN MONTE CARLO (block bootstrap 10 años historia real + ajustes conservadores)**
Horizonte: {horizon_years} años
Capital inicial: ${initial_value:,.0f}
Retiro anual: {withdrawal_str} (crece a {inflation_rate:.1f}% anual)
Inflación considerada: {inflation_rate:.1f}%
{target_str}

**RESULTADOS DE LA SIMULACIÓN (10 000 paths)**
- Mediana final (P50): ${median_terminal:,.0f}
- Escenario pesimista (P10): ${p10_terminal:,.0f}
- Escenario optimista (P90): ${p90_terminal:,.0f}
- Probabilidad de ruina (terminal <= 0): {prob_ruin:.1f}%
- Probabilidad de alcanzar la meta: {prob_target:.1f}%

---

**TAREA:**
Escribí una explicación clara, honesta y accionable en **español natural** (como si hablaras con un cliente inteligente de 45-60 años que quiere entender su plan de verdad).

Estructura la respuesta exactamente así (usá viñetas y lenguaje directo):

**Resumen del plan en una frase**  
**Fortalezas de esta cartera para tu horizonte** (máx 3 bullets)  
**Riesgos reales que deberías entender** (máx 3 bullets, sé brutalmente honesto)  
**Qué significa el escenario pesimista (P10)**  
**Recomendaciones concretas** (máx 3 acciones accionables)  
**Una frase final de prudencia**

Reglas:
- Nunca digas "esto es genial" o "vas a estar tranquilo". Sé conservador.
- Si el P10 es mucho más bajo que el inicial, decilo sin anestesia.
- Si el retiro crece con inflación, mencioná que eso aumenta el riesgo de secuencia.
- Mencioná el perfil de riesgo elegido y por qué importa.
- Longitud total: 180-280 palabras máximo. Sé denso pero legible.

Respondé SOLO con el texto en el formato pedido. Nada de JSON, nada de introducciones extra."""
