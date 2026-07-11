# Análisis de cobertura del universo de activos — Retirement Advisor

| Campo | Valor |
|-------|--------|
| Fecha del análisis | 2026-07-11 |
| Repositorio | `fcalvino/retirement-advisor` |
| Fuente canónica del universo default | `config.py` → `DEFAULT_TICKERS` |
| Espejo UI | `data/universes/default.json` |
| Datos de mercado (candidatos) | yfinance snapshot 2026-07-11 |
| Alcance | Universo default + universos nombrados + gaps + propuesta de 7 tickers |

> **No es consejo de inversión.** Análisis de cobertura y diseño de universo para la plataforma. Las métricas son point-in-time y pueden cambiar.

---

## 1. Resumen del universo actual

### 1.1 Criterio de extracción

Se extrajo el **100%** de los tickers de `DEFAULT_TICKERS` en `config.py` (líneas del bloque “Default universe — edit freely”) y se contrastó con `data/universes/default.json`. Ambos listados son **idénticos**.

```text
len(DEFAULT_TICKERS) == 39
len(set(DEFAULT_TICKERS)) == 39   # sin duplicados
```

### 1.2 Conteo total exacto

| Métrica | Valor |
|---------|------:|
| **Total tickers default** | **39** |
| Únicos | 39 |
| Equities (aprox.) | 34 |
| ETFs | 4 |
| Crypto | 1 |
| ADRs argentinos (bloque config) | 8 |

### 1.3 Listado completo por categoría (orden de `config.py`)

| Categoría (comentario en config) | N | Tickers |
|----------------------------------|---:|---------|
| US Mega-Cap Quality | 7 | `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `NVDA`, `META`, `BRK-B` |
| Financials | 4 | `JPM`, `V`, `MA`, `BAC` |
| Healthcare | 4 | `JNJ`, `UNH`, `ABBV`, `PFE` |
| Consumer Staples | 4 | `PG`, `KO`, `PEP`, `WMT` |
| Industrials / Other | 3 | `HD`, `CAT`, `HON` |
| Dividend Aristocrats | 4 | `O`, `T`, `XOM`, `CVX` |
| ETFs (treated as non-fundamental) | 4 | `SPY`, `QQQ`, `VTI`, `BND` |
| Crypto | 1 | `BTC-USD` |
| Argentina ADRs | 8 | `YPF`, `PAM`, `CEPU`, `LOMA`, `MELI`, `GLOB`, `TEO`, `EDN` |
| **TOTAL** | **39** | |

**Listado plano (orden canónico):**

```text
AAPL, MSFT, GOOGL, AMZN, NVDA, META, BRK-B,
JPM, V, MA, BAC,
JNJ, UNH, ABBV, PFE,
PG, KO, PEP, WMT,
HD, CAT, HON,
O, T, XOM, CVX,
SPY, QQQ, VTI, BND,
BTC-USD,
YPF, PAM, CEPU, LOMA, MELI, GLOB, TEO, EDN
```

### 1.4 Cobertura por `SECTOR_MAP` (intersección con default)

Fuente: `config.py` → `SECTOR_MAP`.

| Sector (mapa interno) | N en default | Tickers en default |
|-----------------------|-------------:|--------------------|
| Technology | 7 | AAPL, MSFT, GOOGL, META, NVDA, MELI, GLOB |
| Consumer Discretionary | 2 | AMZN, HD |
| Financials | 5 | JPM, BRK-B, V, MA, BAC |
| Healthcare | 4 | JNJ, UNH, ABBV, PFE |
| Consumer Staples | 4 | PG, KO, PEP, WMT |
| Energy | 5 | XOM, CVX, YPF, PAM, CEPU |
| Industrials | 3 | CAT, HON, LOMA |
| Telecom / REIT | 3 | T, O, TEO |
| Utilities | 1 | EDN |
| ETF | 4 | SPY, QQQ, VTI, BND |
| Crypto | 1* | BTC-USD (*`SECTOR_MAP` también lista ETH-USD, **no** está en default) |

**Notas de consistencia:**
- Todos los 39 de `DEFAULT_TICKERS` aparecen en `SECTOR_MAP`.
- `ETH-USD` está en `SECTOR_MAP["Crypto"]` y en `CRYPTO_TICKERS`, pero **no** en `DEFAULT_TICKERS`.
- No existe clave **Materials** en `SECTOR_MAP`.

### 1.5 Elegibilidad para el optimizador mean-variance

Fuente: `portfolio/optimizer.py`.

| Filtro | Comportamiento | Impacto en default |
|--------|----------------|--------------------|
| `_ETF_TICKERS` | Excluidos de SLSQP (“sin fundamentals”) | SPY, QQQ, VTI, BND fuera del core optimizado |
| `min_score_threshold` (`OPTIMIZER` = 30) | Score &lt; 30 → excluido | Depende del screener en runtime |
| `_ARS_TICKERS` + `ars_risk_discount` (0.85) | En perfiles conservador/moderado | YPF, PAM, CEPU, LOMA, TEO, EDN (×0.85). **MELI/GLOB no** están en el set ARS |
| `is_crypto` + `max_crypto_pct` | Cap por perfil 3% / 5% / 10% | Solo BTC-USD en default |
| `pre_filter_top_k` | 20 / 30 / 45 por perfil | Universos grandes se recortan antes de SLSQP |
| `max_sector_pct` | 20% / 25% / 30% | Diversificación sectorial hard-constraint |
| `min_dividend_yield_pct` | 3.5 / 2.5 / 1.5 | Perfil Conservador es el más exigente en yield |

**Resumen de elegibilidad estática (default, antes de scores live):**

| Grupo | N | Notas |
|-------|--:|-------|
| ETFs (excluidos SLSQP) | 4 | Útiles para allocation/UI, no para optimización de pesos |
| Crypto | 1 | Cap de crypto |
| ARS descontados | 6 | Riesgo país AR embebido en score compuesto |
| Equities restantes | ~28 | Núcleo US + MELI/GLOB sin descuento ARS |

### 1.6 Universos nombrados (`data/universes/`)

| Key | Nombre | N tickers | Rol |
|-----|--------|----------:|-----|
| `default` | Default | 39 | Universo base (espejo de `DEFAULT_TICKERS`) |
| `dividend_focus` | Dividend Focus | 66 | Aristocrats, REITs, utilities, SCHD/VYM… |
| `growth_moat` | Growth con Moat | 27 | Growth + moat + BTC |
| `latam_adrs` | LATAM ADRs | 27 | AR/BR/MX/CL + EWZ/EWW/ILF |
| `us_quality` | US Quality | 85 | Quality amplia US + ETFs + BTC |
| **Unión** | — | **~167** | Tickers distintos entre todos |

Varios candidatos propuestos abajo **ya existen** en universos no-default (p. ej. COST, NEE, LIN, PLD en `us_quality` / `dividend_focus`), lo que refuerza coherencia interna: no son ideas ajenas al producto, sino huecos del **default** de retiro.

### 1.7 Stack relacionado (no es universo, pero condiciona el análisis)

| Componente | Archivo | Relevancia |
|------------|---------|------------|
| Scoring fundamental 0–100 | `analysis/fundamental.py`, `scoring.py` | ETFs/crypto skip financials |
| Economic Moat 0–20 | `analysis/moat.py` | Bonus capped (`MoatConfig.max_bonus`) |
| Crypto moat | `CryptoMoatConfig` + `crypto_analyzer.py` | ETH ya soportado |
| Tailwinds sector-país | `data/tailwinds/sector_country.json` | Energy AR +8; Utilities AR (EDN) −3 |
| Allocation por edad | `portfolio/allocation.py` | Targets intl 15–25%, REIT, TIPS cerca del retiro |
| Monte Carlo / stress | `portfolio/monte_carlo.py`, `stress_test.py` | Dependen de covarianza del universo elegible |

---

## 2. Análisis de gaps de diversificación

### Gap A — Sin sector Materials / Basic Materials *(significativo)*

| Evidencia | Detalle |
|-----------|---------|
| Código | `SECTOR_MAP` en `config.py` no define clave Materials; ningún ticker default es Basic Materials |
| Contraste | `data/universes/us_quality.json` ya incluye `LIN`, `APD`, `SHW`, `ECL` |
| Impacto retiro | El optimizador no puede asignar peso a un sector con correlación imperfecta vs tech/energy; el constraint `max_sector_pct` no “ve” materials |
| Impacto Moat/score | Se pierden wide-moats clásicos de oligopolio industrial (gases, specialty chemicals) con ROE sostenible |

### Gap B — Utilities de calidad US subrepresentadas *(significativo)*

| Evidencia | Detalle |
|-----------|---------|
| Código | `SECTOR_MAP["Utilities"] = ["EDN"]` únicamente |
| Tailwinds | `utilities-argentina-regulated-tariffs` score **−3** sobre EDN (`data/tailwinds/sector_country.json`) |
| Perfiles | Conservador: `max_volatility_pct=12`, `min_dividend_yield_pct=3.5` — beneficia de utilities US de baja beta |
| Impacto | La única utility del default arrastra **headwind** y riesgo regulatorio AR; no hay ancla defensiva de utilities developed |

### Gap C — Exposición geográfica limitada (casi solo US + Argentina) *(significativo)*

| Evidencia | Detalle |
|-----------|---------|
| Código | Default = blue chips US + ADRs AR + crypto USD; sin developed Europe/Asia |
| Allocation | `AllocationAdvisor` asigna **15–25% international** según edad (`portfolio/allocation.py`) |
| Universos | Intl/LATAM vive en `latam_adrs.json`, no en default |
| Impacto MV/MC | Covarianza y block-bootstrap no exploran correlaciones developed-markets; sesgo home-country US+AR contradice la propia capa de allocation |

### Gap D — Bonos / protección inflacionaria insuficientes *(significativo para retiro)*

| Evidencia | Detalle |
|-----------|---------|
| Código | Solo `BND` en default; `AllocationAdvisor` recomienda TIPS/I-bonds cerca del retiro |
| Optimizador | `BND ∈ _ETF_TICKERS` → **excluido de SLSQP**; no hay TIP/VTIP/TLT en default |
| Impacto | Glide path y perfiles conservadores no tienen instrumento de inflación en el universo base; el mean-variance “elige” solo entre equities (+crypto cap) |

### Gap E — Concentración Tech + crypto incompleto *(complementario)*

| Evidencia | Detalle |
|-----------|---------|
| Código | 7 tickers en Technology (incl. MELI, GLOB); pre_filter favorece scores altos de mega-caps |
| Crypto | `CRYPTO_TICKERS` y moat crypto soportan ETH, pero default solo trae `BTC-USD` |
| Impacto | Factor tech sobrerrepresentado en candidatos al optimizador; stack crypto subutilizado |

---

## 3. Propuesta de nuevos activos (7 tickers)

Criterios de selección alineados a la arquitectura:

1. **Cerrar un gap documentado** (sector, geografía, clase de activo o crypto).
2. **Ser utilizable** por scoring/Moat (equities) o por el path crypto/ETF ya existente.
3. **Respetar restricciones** del optimizador (`max_crypto_pct`, exclusión de ETFs, `min_div`, caps sectoriales).
4. Preferir nombres **ya presentes** en otros universos del repo cuando sea posible (coherencia).

### 3.1 Tabla de candidatos

Métricas: snapshot **yfinance 2026-07-11** (point-in-time). DY = dividend yield normalizado cuando el feed es confiable.

| # | Ticker | Clase | País / sector (yfinance) | Métricas clave | Gap que cierra | Impacto esperado en la plataforma |
|---|--------|-------|---------------------------|----------------|----------------|-----------------------------------|
| 1 | **COST** | Equity | US / Consumer Defensive | ROE **29.2%**, β **0.87**, PE ~46, DY ~**0.6%**, mcap ~$406B | Quality defensivo vs solo WMT; diversifica consumer | Wide-moat membership; eleva fundamental/Moat; β moderado ayuda vol; yield bajo → más valor en Moderado/Agresivo que en Conservador puro income |
| 2 | **NEE** | Equity | US / Utilities | ROE **10.3%**, NM **29.4%**, β **0.67**, PE ~22, DY ~**2.7%**, mcap ~$183B | **Gap B** Utilities calidad | Baja β mejora frontier conservadora; ancla defensiva sin headwind AR; DY contribuye a constraint de ingreso |
| 3 | **LIN** | Equity | UK / Basic Materials | ROE **18.2%**, NM **20.4%**, β **0.72**, PE ~35, DY ~**1.2%**, mcap ~$245B | **Gap A** Materials + **Gap C** intl | Nueva clave sectorial `Materials`; oligopolio gases (moat); correlación imperfecta con tech/energy |
| 4 | **NVO** | Equity | Denmark / Healthcare | ROE **71.4%**, NM **37.2%**, β **0.36**, PE ~**11.9**, mcap ~$219B | **Gap C** intl + depth healthcare | Excelente proxy de calidad/crecimiento con **β muy bajo** y valuación más razonable vs mega-growth US; DY del ADR es ruidoso en yfinance — priorizar ROE/márgenes/β |
| 5 | **PLD** | Equity REIT | US / Real Estate | NM **39.7%**, DY ~**2.9%**, PE ~35, β **1.34**, mcap ~$134B | REIT solo-`O` | Diversifica real estate (industrial/logistics vs net-lease retail de O); income para Conservador/Moderado; AllocationAdvisor pide REIT 5–25% |
| 6 | **ETH-USD** | Crypto | — | mcap ~$220B; type CRYPTOCURRENCY | **Gap E** crypto stack | Ya en `CRYPTO_TICKERS` / normalize / crypto moat; diversifica factor digital vs BTC-only; hard-cap `max_crypto_pct` (3–10%) |
| 7 | **TIP** | Bond ETF | — / TIPS | type ETF; yield feed variable | **Gap D** inflación / bonos | Visible en screener/allocation/stress; **debe** ir a `_ETF_TICKERS` (excluido de SLSQP, igual que BND) |

### 3.2 Justificación por ticker (retiro + Moat + MV + riesgo)

#### COST — Costco
- **Moat:** modelo de membresía con tasas de renovación históricamente muy altas; scale + cost leadership (literatura wide-moat retail).
- **Scoring:** ROE ~29% supera umbrales `roe_excellent` (20%) en `FundamentalThresholds`.
- **MV:** β &lt; 1 reduce contribución a vol vs NVDA/META; baja correlación sectorial perfecta con staples actuales (PG/KO/PEP).
- **Restricción:** DY bajo — no cuenta mucho para `min_dividend_yield_pct=3.5` del Conservador; sí para crecimiento de capital a largo plazo.

#### NEE — NextEra Energy
- **Moat:** utilidad regulada + liderazgo en renovables US (escala y rate base).
- **Retiro:** β ~0.67 es de los más bajos entre candidatos; encaja `max_volatility_pct=12` conservador.
- **Vs EDN:** evita el headwind −3 de utilities AR; aporta utility **positiva** al mapa sectorial.
- **MV:** sector Utilities casi vacío → el constraint sectorial no compite con 7 tech names.

#### LIN — Linde
- **Moat:** oligopolio global de gases industriales (switching costs + density de plantas).
- **Gap sectorial:** habilita clave `Materials` en `SECTOR_MAP` (hoy inexistente).
- **Geografía:** domicilio UK → partial close de Gap C con equity real (no solo ETF).
- **Score:** ROE ~18% y márgenes ~20% suelen puntuar bien en profitability.

#### NVO — Novo Nordisk
- **Moat:** franchise metabólica/diabetes (propiedad intelectual + escala comercial).
- **Retiro:** β ~0.36 + PE ~12 (snapshot) es inusualmente atractivo vs growth US; diversifica healthcare más allá de JNJ/UNH/ABBV/PFE.
- **MV:** low-beta + país developed distinto mejora frontera media-varianza.
- **Nota de datos:** el DY del ADR en yfinance puede distorsionarse; el optimizador usa yield de info — validar en screener live antes de confiar en el constraint de dividendos.

#### PLD — Prologis
- **Moat:** red global de logística / e-commerce warehousing.
- **Vs O:** O es net-lease retail-ish con DY ~5.1%; PLD aporta **industrial REIT** y mejor alineación con demanda estructural de supply chain.
- **Retiro:** DY ~2.9% ayuda Moderado; β 1.34 es más alto — el cap `max_position_pct` limita el daño.
- **Allocation:** alimenta el bucket `real_estate_pct` del advisor de edad.

#### ETH-USD — Ethereum
- **Arquitectura:** `is_crypto`, `normalize_crypto_ticker`, `CryptoMoatConfig`, path en `crypto_analyzer` — **cero cambios de pipeline**.
- **Diversificación:** reduce dependencia de un solo factor crypto (BTC).
- **Riesgo:** vol alta; `max_crypto_pct` y `max_vol_for_buy` ya acotan BUY en retiro. En horizontes cortos, goal-aware optimizer recorta crypto aún más.

#### TIP — iShares TIPS Bond ETF
- **Retiro:** la propia `allocation.py` recomienda TIPS cerca del retiro; hoy el default no ofrece el instrumento.
- **Arquitectura:** igual que BND — no entra a SLSQP; sí a universo, About, allocation mental model y posibles stress paths de “bonos”.
- **Integración obligatoria:** agregar a `_ETF_TICKERS` y `SECTOR_MAP["ETF"]` para no romper el filtro “no fundamentals”.

### 3.3 Impacto agregado esperado (cualitativo, medible post-integración)

| Dimensión | Antes (default 39) | Después (propuesta 46) |
|-----------|--------------------|-------------------------|
| Sectores mapeados “llenos” | Sin Materials; Utilities=1 (EDN) | Materials=LIN; Utilities=EDN+NEE |
| Geografía equity | US + AR | + UK (LIN), + DK (NVO) |
| REIT | Solo O | O + PLD (estilos distintos) |
| Crypto | BTC | BTC + ETH |
| Bonos | Solo BND | BND + TIP (inflación) |
| Candidatos SLSQP (estático) | ~34 equities/crypto | ~39 (+COST,NEE,LIN,NVO,PLD,ETH; TIP excluido) |
| Alineación con AllocationAdvisor | Intl/REIT/TIPS sub-cubiertos | Mejor cobertura de targets de edad |

### 3.4 Candidatos descartados (conscientes)

| Ticker | Motivo de no incluir en esta tanda |
|--------|-------------------------------------|
| LLY | Solapa “pharma growth” con NVO; valuación más exigente; se priorizó diversificación geográfica |
| ASML | Moat semi europeo fuerte, pero refuerza sesgo tech ya alto (NVDA) |
| VXUS | Buen proxy intl ETF, pero NVO+LIN ya aportan equity intl al optimizador |
| MCD / SPGI | Quality US ya bien cubierto; menor gap estructural vs materials/utilities/TIPS |

---

## 4. Snippet listo para integrar

### 4.1 `config.py` — `DEFAULT_TICKERS` (reemplazo del bloque)

```python
# Default universe — edit freely
DEFAULT_TICKERS: List[str] = [
    # US Mega-Cap Quality
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B",
    # Financials
    "JPM", "V", "MA", "BAC",
    # Healthcare
    "JNJ", "UNH", "ABBV", "PFE", "NVO",
    # Consumer Staples / Defensive quality
    "PG", "KO", "PEP", "WMT", "COST",
    # Industrials / Other
    "HD", "CAT", "HON",
    # Materials (sector gap fill)
    "LIN",
    # Dividend Aristocrats / REIT
    "O", "T", "XOM", "CVX", "PLD",
    # Utilities (US quality + AR)
    "NEE",
    # ETFs (treated as non-fundamental)
    "SPY", "QQQ", "VTI", "BND", "TIP",
    # Crypto
    "BTC-USD", "ETH-USD",
    # Argentina ADRs
    "YPF", "PAM", "CEPU", "LOMA", "MELI", "GLOB", "TEO", "EDN",
]
# Expected count after expansion: 46
```

### 4.2 `config.py` — `SECTOR_MAP` (actualización sugerida)

```python
SECTOR_MAP: Dict[str, List[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "MELI", "GLOB"],
    "Consumer Discretionary": ["AMZN", "HD"],
    "Financials": ["JPM", "BRK-B", "V", "MA", "BAC"],
    "Healthcare": ["JNJ", "UNH", "ABBV", "PFE", "NVO"],
    "Consumer Staples": ["PG", "KO", "PEP", "WMT", "COST"],
    "Energy": ["XOM", "CVX", "YPF", "PAM", "CEPU"],
    "Industrials": ["CAT", "HON", "LOMA"],
    "Materials": ["LIN"],  # NEW
    "Telecom / REIT": ["T", "O", "TEO", "PLD"],
    "Utilities": ["EDN", "NEE"],
    "ETF": ["SPY", "QQQ", "VTI", "BND", "TIP"],
    "Crypto": ["BTC-USD", "ETH-USD"],
}
```

### 4.3 `data/universes/default.json`

```json
{
  "name": "Default",
  "description": "Universo base: blue chips US + quality/moat fills + ETFs core/TIPS + ADRs argentinos + crypto BTC/ETH.",
  "tickers": [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B",
    "JPM", "V", "MA", "BAC",
    "JNJ", "UNH", "ABBV", "PFE", "NVO",
    "PG", "KO", "PEP", "WMT", "COST",
    "HD", "CAT", "HON",
    "LIN",
    "O", "T", "XOM", "CVX", "PLD",
    "NEE",
    "SPY", "QQQ", "VTI", "BND", "TIP",
    "BTC-USD", "ETH-USD",
    "YPF", "PAM", "CEPU", "LOMA", "MELI", "GLOB", "TEO", "EDN"
  ]
}
```

### 4.4 `portfolio/optimizer.py` — mantener exclusión de ETFs

```python
# ETF tickers — excluded from optimization (no fundamentals)
_ETF_TICKERS = {"SPY", "QQQ", "VTI", "BND", "GLD", "SLV", "TLT", "IEF", "TIP"}
```

> **Importante:** `ETH-USD` **no** va en `_ETF_TICKERS`. Ya lo maneja `is_crypto`.

### 4.5 Checklist de integración (cuando se aplique en código)

- [ ] Actualizar `DEFAULT_TICKERS` y `SECTOR_MAP` en `config.py`
- [ ] Actualizar `data/universes/default.json` (mismo orden/conteo)
- [ ] Añadir `TIP` a `_ETF_TICKERS` en `portfolio/optimizer.py`
- [ ] Verificar `len(DEFAULT_TICKERS) == len(load_universe("default")) == 46`
- [ ] Smoke: screener sobre nuevos tickers; optimizer no debe incluir TIP/SPY/…
- [ ] Tests: `./venv/bin/python3 -m pytest tests/test_optimizer.py tests/test_config_validator.py -q`
- [ ] (Opcional) Añadir tailwind curado para utilities US / materials si se desea score de cola de viento

### 4.6 Solo las adiciones (diff mental)

```python
NEW = ["COST", "NEE", "LIN", "NVO", "PLD", "ETH-USD", "TIP"]
# 39 + 7 = 46
```

---

## 5. Verificación de criterios de éxito

| Criterio | Estado | Evidencia en este documento |
|----------|--------|------------------------------|
| **C1** — 100% de tickers del universo default listados, conteo exacto, categorías y ejemplos | ✅ | §1.2–1.3: **39** tickers, 9 categorías, listado completo plano y por bloque |
| **C2** — ≥3 gaps significativos con evidencia de código/datos | ✅ | §2: Gaps **A, B, C** (y D, E); citas a `SECTOR_MAP`, tailwinds, `allocation.py`, `_ETF_TICKERS` |
| **C3** — 5–8 tickers propuestos con justificación medible | ✅ | §3: **7** tickers (COST, NEE, LIN, NVO, PLD, ETH-USD, TIP) con métricas yfinance + impacto Moat/MV/restricciones |
| **C4** — Artefacto accionable MD + snippet config | ✅ | Este archivo + §4 snippets listos para pegar |

### Iteraciones del análisis

| Iter | Acción | Resultado |
|------|--------|-----------|
| 1 | Extracción de `config.py` / universos / optimizer / allocation; snapshot candidatos | C1–C3 cumplidos en análisis; C4 pendiente de artefacto |
| 2 | Re-fetch métricas limpias (ROE/β/DY) + redacción del artefacto final | **C1–C4 verificados positivamente** |

---

## 6. Conclusión y siguiente paso recomendado

El universo **default de 39 tickers** cubre bien mega-caps US, financials de calidad, un set corto de healthcare/staples, energy (US+AR), un REIT (`O`), bonos genéricos (`BND`) y BTC, más un bloque denso de ADRs argentinos. Para un **Retirement Advisor** que ya predica allocation internacional, REIT y TIPS, y que optimiza con caps sectoriales y de crypto, los gaps **Materials, Utilities US, equity developed, TIPS e ETH** son los de mayor ROI de cobertura.

**Propuesta operativa:** integrar los 7 tickers del §4 (universo → 46), manteniendo ETFs fuera del SLSQP y crypto bajo `max_crypto_pct`. Validar en screener live (especialmente yield de NVO ADR) antes de usar el constraint de dividendos del perfil Conservador como única señal.

---

*Generado como artefacto de análisis de cobertura. Fuentes de código: `config.py`, `data/universes/*`, `portfolio/optimizer.py`, `portfolio/allocation.py`, `data/tailwinds/sector_country.json`, `analysis/fundamental.py`.*
