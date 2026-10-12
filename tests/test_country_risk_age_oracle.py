"""Oráculo COUNTRY-RISK-AGE: el riesgo país es un dato diario y avisa cuando envejece.

El riesgo país de Argentina se mide en meses como una Fuente de gestora (vieja a los
12, fuera a los 24), pero su serie publica a diario: el 2026-10-12 la nota seguía
diciendo «655 pb al 2026-10-02» sin una palabra sobre sus 10 días, aunque la fuente
ya traía 589 pb al 2026-10-09. La fecha estaba, la antigüedad no.

Cuentas a mano: del 2026-10-02 al 2026-10-12 hay 10 días. El dato se sigue usando
(la regla de los meses no cambia); lo que cambia es que el aviso nombra los días y
dice cómo refrescarlo.
"""

from __future__ import annotations

from datetime import date, timedelta

from analysis.estimacion import country_warnings, estimate_asset
from analysis.fuentes import CountryRisk
from config import FUENTES

AS_OF = date(2026, 10, 2)
CENTRALS = {"emerging": 7.225}
INFLATION = 2.36


def _est(today):
    risks = {"Argentina": CountryRisk(country="Argentina", value_bp=655, as_of=AS_OF,
                                      source="https://x.org")}
    return estimate_asset("YPF", "emerging", centrals=CENTRALS, inflation=INFLATION,
                          country="Argentina", country_risks=risks, today=today)


def test_a_ten_day_old_spread_says_so():
    e = _est(date(2026, 10, 12))
    assert "10 días" in e.country_note
    assert "refresh_fuentes.py" in e.country_note


def test_the_old_spread_is_still_subtracted():
    """Avisar no es esconder ni descartar: el 655 sigue restándose, con piso en 0 % real."""
    e = _est(date(2026, 10, 12))
    assert e.annual_pct == INFLATION
    assert "655 pb al 2026-10-02" in e.country_note


def test_the_warning_reaches_the_screen_lines():
    e = _est(date(2026, 10, 12))
    assert any("10 días" in line for line in country_warnings([e]))


def test_the_limit_is_in_config_not_in_the_code():
    limit = FUENTES.country_risk_warn_days
    assert "días" not in _est(AS_OF + timedelta(days=limit)).country_note
    assert f"{limit + 1} días" in _est(AS_OF + timedelta(days=limit + 1)).country_note
