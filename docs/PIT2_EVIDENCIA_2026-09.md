# PIT-2 — Evidencia point-in-time del Piotroski (1 año)

> Generado 2026-09-26 20:24 UTC desde `83148cb` con `scripts/pit_evidence_report.py`. Auditoría histórica: no se actualiza, se regenera.

- **Universos:** default, global_quality
- **Cortes con filas:** 27 (2012-06-01 → 2025-06-01)
- **Filas:** 1350
- **Horizonte:** 365 días calendario; exceso contra `SPY` (cierre ajustado, retorno total)
- **Grupos (cortes del motor):** fuerte ≥ 7 (+12 pts), aceptable ≥ 5 (+6), débil < 5

**Sesgo de supervivencia.** Los tickers salen de universos curados hoy y el mapa ticker→CIK de la SEC es el vigente: una empresa que quebró o fue absorbida antes de hoy casi nunca está en la muestra. Los deslistados que sí entran quedan marcados (`delisted_before_horizon`) y sin outcome. Sólo filers de la SEC (10-K): los listados locales, ADRs 20-F, ETFs y cripto de los universos no tienen fila.

## Por grupo

| Grupo | Filas | Con exceso | Exceso medio ± banda 95 % | % que le ganó al benchmark |
|---|---:|---:|---|---:|
| fuerte | 197 | 197 | +9.33 % ± 5.23 | 58.4 % |
| aceptable | 444 | 444 | +3.51 % ± 2.48 | 50.5 % |
| débil | 709 | 679 | +6.10 % ± 3.15 | 50.1 % |

Las filas de un mismo corte comparten el mercado de ese año: estas bandas, calculadas por fila, son **más angostas de lo que la muestra justifica**. La comparación que cuenta es la de abajo.

## Fuerte − débil, por corte

Unidad: el corte (media del grupo fuerte − media del débil en cada fecha). Cortes con los dos grupos: **27**. Diferencia media: **+2.89 % ± 8.08**.

Cortes a menos de un horizonte de distancia comparten parte del mismo año de mercado (con la grilla por defecto, cada 6 meses sobre 1 año, medio año): tampoco son del todo independientes, así que esta banda también es algo optimista. Un veredicto «inconcluso» con esta banda lo sería con más razón con la honesta.

**Veredicto: inconcluso.**

| Corte | Fuerte − débil |
|---|---:|
| 2012-06-01 | -11.38 pp |
| 2012-12-01 | -36.00 pp |
| 2013-06-01 | -24.46 pp |
| 2013-12-01 | +10.34 pp |
| 2014-06-01 | +10.21 pp |
| 2014-12-01 | +0.17 pp |
| 2015-06-01 | +6.62 pp |
| 2015-12-01 | +12.03 pp |
| 2016-06-01 | +30.80 pp |
| 2016-12-01 | +29.46 pp |
| 2017-06-01 | +10.44 pp |
| 2017-12-01 | +11.40 pp |
| 2018-06-01 | -1.30 pp |
| 2018-12-01 | +21.66 pp |
| 2019-06-01 | +48.45 pp |
| 2019-12-01 | +23.16 pp |
| 2020-06-01 | +12.75 pp |
| 2020-12-01 | +11.78 pp |
| 2021-06-01 | -22.78 pp |
| 2021-12-01 | -43.34 pp |
| 2022-06-01 | -6.62 pp |
| 2022-12-01 | -8.83 pp |
| 2023-06-01 | -1.86 pp |
| 2023-12-01 | -18.85 pp |
| 2024-06-01 | +5.57 pp |
| 2024-12-01 | +5.40 pp |
| 2025-06-01 | +3.16 pp |

## Estado de los outcomes

| Estado | Filas |
|---|---:|
| `no_price` | 30 |
| `scored` | 1320 |

## Qué no dice este reporte

- No recalibra nada: mover `PiotroskiConfig.strong_threshold`/`bonus_strong` es U5-1b, una decisión humana con esta tabla sobre la mesa.
- La mitad «moat» de U5-1b queda fuera: reconstruir el tramo IA del pasado con un modelo que ya sabe qué pasó después es hindsight bias.
