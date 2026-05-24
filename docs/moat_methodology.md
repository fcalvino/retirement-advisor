# Economic Moat Methodology

> **Módulo:** `analysis/moat.py` | **Config:** `config.py → MoatConfig`

## ¿Qué es un Economic Moat?

El término fue popularizado por Warren Buffett para describir una **ventaja competitiva duradera** que protege la rentabilidad de una empresa de la competencia, similar a un foso que rodea un castillo. Una empresa con un moat amplio puede generar retornos sobre el capital superiores al costo de capital durante 20 años o más.

Para una cartera de retiro, el moat es crítico: queremos empresas que en 15-20 años sigan siendo líderes en su industria, no empresas que hoy son rentables pero mañana pueden ser desplazadas.

---

## Estructura del Score (0–20 pts)

```
Moat Total = Cuantitativo (0–12) + Cualitativo AI (0–8)
```

### Capa 1: Cuantitativo (0–12 pts)

Calculado automáticamente a partir de estados financieros (yfinance). **Sin llamadas a AI, siempre disponible.**

| Dimensión | Pts | Qué mide | Umbrales |
|---|---|---|---|
| Gross Margin nivel | 0–2 | Pricing power actual | ≥50%=2, ≥35%=1, ≥20%=0.5 |
| Gross Margin estabilidad | 0–2 | Durabilidad del pricing power | std ≤3pp=2, ≤8pp=1, ≤15pp=0.5 |
| ROIC sostenido | 0–2 | Capital allocation moat | avg ≥20%=2, ≥12%=1, ≥8%=0.5 |
| Revenue defensividad | 0–2 | Resiliencia ante recesiones | 0 años negativos=2, 1 año=1, ≤2=0.5 |
| FCF Conversion | 0–2 | Calidad de ganancias | OCF/NI ≥1.2=2, ≥0.9=1, ≥0.6=0.5 |
| FCF Margin | 0–2 | Escalabilidad del modelo | FCF/Rev ≥20%=2, ≥10%=1, ≥5%=0.5 |

**Empresas de referencia — Cuantitativo:**
- MSFT: 12/12 (perfecto — software con márgenes 65%+, ROIC >30%, sin caídas de revenue)
- MELI: 11/12 (excelente — GM moderado por mix de negocio, pero ROIC y FCF sólidos)
- YPF:   2/12 (bajo — energía con márgenes comprimidos por regulación de precios)

### Capa 2: Cualitativo AI (0–8 pts)

Evaluado por un LLM con contexto de la empresa. **Cacheado 7 días por ticker.** Solo se activa cuando hay un proveedor AI configurado en Settings.

| Dimensión | Pts | Qué mide | Ejemplos |
|---|---|---|---|
| Brand Strength | 0–2 | Reconocimiento y poder de pricing de marca | Apple=2, YPF=1, genérico=0 |
| Network Effects | 0–2 | Valor aumenta con más usuarios (Metcalfe) | Visa=2, MELI=2, manufactura=0 |
| Switching Costs | 0–2 | Fricción para cambiar de proveedor | SAP=2, Bloomberg=2, commodity=0 |
| Regulatory / IP | 0–2 | Patentes, licencias o barreras regulatorias | pharma con patentes=2, YPF concesiones=1.5 |

**Rúbrica de scoring AI:**
- `2.0` = Ventaja dominante, duradera y reconocible globalmente
- `1.5` = Ventaja real con alguna limitación o riesgo específico
- `1.0` = Ventaja moderada, presente pero no dominante
- `0.5` = Ventaja incipiente o débil, podría erosionarse en 5 años
- `0.0` = Sin ventaja identificable

**Descuento para mercados emergentes:** el LLM aplica automáticamente −0.5 en dimensiones afectadas por riesgo político o macro (Argentina, Venezuela, etc.).

---

## Clasificaciones

| Clasificación | Score | Descripción |
|---|---|---|
| 🏰 **Wide Moat** | ≥ 14/20 | Ventaja duradera 20+ años — capital allocation para largo plazo |
| 🟢 **Narrow Moat** | ≥ 8/20 | Ventaja sólida ~10 años — monitorear competencia y disrupción |
| 🟡 **Minimal Moat** | ≥ 4/20 | Alguna protección pero erosionándose — revisión anual recomendada |
| ⚪ **No Moat** | < 4/20 | Sin ventaja competitiva identificable — evitar para retiro |

---

## Bonus aplicado al Score Ajustado

```
moat_bonus = min(moat_total × 0.5, 10.0)
adjusted_score = base + consistency + piotroski_bonus + moat_bonus  (cap 100)
```

El bonus está **intencionalmente capeado en +10 pts** para que el moat complemente —pero no domine— el análisis fundamental cuantitativo. Una empresa con Wide Moat pero fundamentals pobres (P/E 80x, deuda alta) no debería ser BUY solo por el moat.

**Ejemplo — MELI:**
- Base Score: 41/100 (penalizado por P/E 44x)
- Consistency: +10
- Piotroski 5/9: +6
- Moat Wide 17.5/20: **+8.8 pts**
- **Score Ajustado: 65.8 → BUY** ✅

Sin el moat, MELI quedaría en ~57 pts (HOLD). Con el moat Wide refleja correctamente que es el operador dominante de e-commerce y fintech en LatAm con network effects masivos.

---

## Caching y Costo AI

| Aspecto | Detalle |
|---|---|
| Cache backend | SQLite (misma DB que el resto del sistema) |
| TTL | 7 días por (ticker, provider, model) |
| Clave de cache | `moat_ai_{symbol}_{provider}_{model}` |
| Fallo de API | Fallback graceful a cuantitativo-only (sin excepción al usuario) |
| Screener | Siempre usa cuantitativo-only (sin costo, rápido) |
| Stock Analysis | Llama AI si está configurado; usa cache si existe |

El análisis de MSFT con Grok (512 tokens) cuesta ~$0.001 y es válido por 7 días. Con 40 tickers en el universo, el costo total de un análisis completo con AI es < $0.05.

---

## Ejemplos Reales (Grok grok-4.20, Mayo 2026)

| Ticker | Quant | AI | Total | Clasificación | Bonus |
|---|---|---|---|---|---|
| MSFT | 12.0/12 | 7.5/8 | 19.5/20 | 🏰 Wide | +9.8 pts |
| MELI | 11.0/12 | 6.5/8 | 17.5/20 | 🏰 Wide | +8.8 pts |
| AAPL | ~11/12 | ~7.5/8 | ~18.5/20 | 🏰 Wide | ~+9.3 pts |
| YPF | 2.0/12 | 3.0/8 | 5.0/20 | 🟡 Minimal | +2.5 pts |

**Nota de Grok sobre YPF:** *"Su principal moat cualitativo es regulatory: concesiones de explotación otorgadas por el Estado argentino y posición de casi-monopolio en refinación (Vaca Muerta), aunque atenuado por riesgo político y macro del país."*

---

## Ajuste de Umbrales

Los umbrales de clasificación se pueden ajustar en `config.py → MoatConfig` sin tocar el código de análisis:

```python
@dataclass
class MoatConfig:
    wide_threshold: float = 14.0    # bajar a 12 para ser más generoso con "Wide"
    narrow_threshold: float = 8.0
    minimal_threshold: float = 4.0
    max_bonus: float = 10.0         # subir para dar más peso al moat en el score final
    ai_cache_ttl_hours: int = 168   # reducir para re-evaluar más frecuentemente
```

---

## Limitaciones Conocidas

1. **Datos anuales de yfinance:** el cuantitativo usa hasta 4 años de historia. Empresas recientes o con cambios de modelo pueden no reflejar el moat actual.

2. **Sin datos históricos de moat:** el score refleja el moat *actual*, no la trayectoria. Una empresa que destruyó su moat en los últimos 2 años puede aún puntuar bien si los 4 años previos eran sólidos.

3. **LLM sin datos en tiempo real:** el análisis AI se basa en el entrenamiento del modelo + la descripción de yfinance. Para noticias recientes (adquisiciones, cambios regulatorios), el análisis puede quedar desactualizado. Invalidar el cache manualmente desde Settings si hay eventos materiales.

4. **Sector-agnostic thresholds:** los umbrales cuantitativos son los mismos para software y energía. Una empresa energética "excelente" con GM=30% puntuaría menos que una SaaS promedio con GM=65%, lo cual es correcto desde una perspectiva de moat comparativo.
