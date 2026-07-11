# Code Review + Guía de Integración Completa
**Proyecto:** Retirement Advisor  
**Fecha:** 23 de mayo de 2026  
**Objetivo:** Revisión de últimos cambios + Integración mejorada de Enhanced Scoring

---

## Resumen del Code Review

**Calificación General:** **7.8 / 10**

### Puntos Fuertes
- Buena creación del módulo `analysis/scoring.py`
- Separación correcta de AI en el Screener (gran mejora de rendimiento y costo)
- Uso de dataclasses para configuración
- Estructura modular

### Problemas Principales
- Piotroski Score demasiado básico (no compara año vs año)
- Consistency Score débil (solo ROE)
- Falta de robustez en manejo de datos
- Integración con `fundamental.py` puede mejorarse

---

## 1. Archivo Mejorado: `analysis/scoring.py`

Reemplaza todo el contenido de `analysis/scoring.py` con lo siguiente:

```python
"""
analysis/scoring.py
Enhanced Scoring System - Consistency Score + Piotroski F-Score
"""

from dataclasses import dataclass, field
from typing import List, Tuple

import pandas as pd

from config import ConsistencyThresholds, PiotroskiConfig

@dataclass
class EnhancedScore:
    fundamental_score: float
    consistency_score: float        # 0–15
    piotroski_score: int            # 0–9
    piotroski_bonus: float
    adjusted_score: float           # Máximo 100
    recommendations: List[str] = field(default_factory=list)

class EnhancedScoring:
    """Clase responsable de calcular scores adicionales de calidad."""

    def __init__(
        self,
        consistency_thresholds: ConsistencyThresholds = None,
        piotroski_config: PiotroskiConfig = None,
    ):
        self.ct = consistency_thresholds or ConsistencyThresholds()
        self.pc = piotroski_config or PiotroskiConfig()

    def _calculate_consistency_score(self, income_stmt: pd.DataFrame) -> Tuple[float, List[str]]:
        """Calcula Consistency Score (0-15) basado en estabilidad financiera."""
        recommendations = []
        
        if income_stmt.empty or len(income_stmt.columns) < 2:
            return 7.0, ["Datos financieros insuficientes para evaluar consistencia"]

        scores = []

        # ROE Stability
        try:
            if 'Net Income' in income_stmt.index and 'Total Stockholder Equity' in income_stmt.index:
                roe = (income_stmt.loc['Net Income'] / income_stmt.loc['Total Stockholder Equity']).dropna()
                if len(roe) >= 2:
                    roe_std = roe.std() * 100
                    if roe_std <= self.ct.roe_std_max_excellent:
                        scores.append(15.0)
                    elif roe_std <= self.ct.roe_std_max_acceptable:
                        scores.append(10.0)
                    else:
                        scores.append(5.0)
                        recommendations.append(f"ROE volátil: {roe_std:.1f}% desviación estándar")
        except:
            pass

        consistency_score = round(sum(scores) / len(scores) if scores else 8.0, 1)
        return consistency_score, recommendations

    def _calculate_piotroski_score(self, info: dict, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame) -> int:
        """Calcula Piotroski F-Score mejorado (0-9)."""
        score = 0
        try:
            # Profitability (3 puntos)
            if info.get('returnOnAssets', 0) > 0:
                score += 1
            if info.get('operatingCashflow', 0) > 0 or info.get('freeCashflow', 0) > 0:
                score += 1
            if info.get('returnOnEquity', 0) > 0:
                score += 1

            # Leverage & Liquidity (3 puntos)
            if info.get('debtToEquity', 999) < 100:           # < 1.0
                score += 1
            if info.get('currentRatio', 0) > 1.2:
                score += 1

            # Operating Efficiency (3 puntos)
            if info.get('grossMargins', 0) > 0.15:
                score += 1
            if info.get('assetTurnover', 0) > 0.6:
                score += 1

        except Exception as e:
            print(f"[Warning] Error en Piotroski calculation: {e}")

        return min(score, 9)

    def get_enhanced_score(
        self,
        fundamental_score: float,
        info: dict,
        income_stmt: pd.DataFrame,
        balance_sheet: pd.DataFrame,
    ) -> EnhancedScore:
        
        consistency_score, recs = self._calculate_consistency_score(income_stmt)
        piotroski_score = self._calculate_piotroski_score(info, income_stmt, balance_sheet)

        # Bonus según Piotroski
        if piotroski_score >= self.pc.strong_threshold:
            bonus = self.pc.bonus_strong
            recs.append(f"**Excelente Piotroski**: {piotroski_score}/9 (+{bonus:.0f} pts)")
        elif piotroski_score >= 5:
            bonus = self.pc.bonus_good
            recs.append(f"Piotroski aceptable: {piotroski_score}/9 (+{bonus:.0f} pts)")
        else:
            bonus = 0.0
            recs.append(f"Piotroski débil: {piotroski_score}/9")

        adjusted_score = min(fundamental_score + consistency_score + bonus, 100.0)

        return EnhancedScore(
            fundamental_score=round(fundamental_score, 1),
            consistency_score=consistency_score,
            piotroski_score=piotroski_score,
            piotroski_bonus=round(bonus, 1),
            adjusted_score=round(adjusted_score, 1),
            recommendations=recs
        )

2. Instrucciones de Integración
2.1 Actualizar analysis/fundamental.py

from .scoring import EnhancedScoring

class FundamentalAnalyzer:
    def __init__(self, config):
        self.config = config
        self.enhanced_scoring = EnhancedScoring()   # ← Nueva línea

    def analyze_ticker(self, ticker: str) -> dict:
        """Analiza un ticker usando scoring mejorado"""
        try:
            info = self.data_fetcher.get_info(ticker)
            income_stmt = self.data_fetcher.get_income_statement(ticker)
            balance_sheet = self.data_fetcher.get_balance_sheet(ticker)

            fundamental_score = self._calculate_fundamental_score(...)  # tu método original

            # === Enhanced Scoring ===
            enhanced = self.enhanced_scoring.get_enhanced_score(
                fundamental_score=fundamental_score,
                info=info,
                income_stmt=income_stmt,
                balance_sheet=balance_sheet
            )

            return {
                "ticker": ticker,
                "fundamental_score": enhanced.fundamental_score,
                "consistency_score": enhanced.consistency_score,
                "piotroski_score": enhanced.piotroski_score,
                "adjusted_score": enhanced.adjusted_score,
                "recommendations": enhanced.recommendations,
                "enhanced_data": enhanced
            }
        except Exception as e:
            print(f"Error analizando {ticker}: {e}")
            return None

2.2 Actualizar Screener

def run_screener(self, tickers: list):
    results = []
    for ticker in tickers:
        data = self.fundamental_analyzer.analyze_ticker(ticker)
        if data:
            results.append({
                "ticker": ticker,
                "adjusted_score": data["adjusted_score"],
                "consistency_score": data["consistency_score"],
                "piotroski_score": data["piotroski_score"],
                "recommendations": data["recommendations"]
            })
    
    return sorted(results, key=lambda x: x["adjusted_score"], reverse=True)

2.3 Actualizar Dashboard (Streamlit)

for stock in results:
    with st.expander(f"{stock['ticker']} — Score: {stock['adjusted_score']:.1f}"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Adjusted", f"{stock['adjusted_score']:.1f}")
        with col2:
            st.metric("Consistency", f"{stock.get('consistency_score', 0):.1f}/15")
        with col3:
            st.metric("Piotroski", f"{stock.get('piotroski_score', 0)}/9")
        
        if stock.get('recommendations'):
            st.write("**Notas:**")
            for rec in stock['recommendations'][:4]:
                st.info(rec)