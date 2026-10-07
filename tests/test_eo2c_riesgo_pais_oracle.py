"""Oráculo EO-2c: el riesgo país de Argentina como dato fechado y citado (ADR 0001).

Decisiones del usuario (2026-10-05):
- Entra como dato, no como rendimiento esperado: no toca la mediana ni el
  Desacuerdo de emergentes. (EO-4d lo convierte en la Estimación de un ADR argentino
  y borra ``OPTIMIZER.ars_risk_discount``: ``test_eo4d_riesgo_pais_estimacion_oracle``.)
- La antigüedad sigue las reglas de ``FUENTES``: aviso a los 12 meses, fuera a los 24.

El dato es el EMBI de J.P. Morgan para Argentina que publica Ámbito, por
ArgentinaDatos (Ámbito bloquea el acceso directo). Lo escribe
``scripts/refresh_fuentes.py``; la app no sale a la red para mostrarlo.

Los números esperados están hechos a mano en cada test.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

TODAY = date(2026, 10, 5)


# --------------------------------------------------------------------------- #
#  El dato: la última observación, con su fecha y su unidad                    #
# --------------------------------------------------------------------------- #

def test_the_entry_is_the_last_observation_up_to_today():
    from analysis.fuentes import country_risk_entry

    obs = [(date(2026, 10, 2), 655.0), (date(2026, 9, 30), 640.0), (date(2026, 10, 1), 660.0)]
    e = country_risk_entry(obs, today=TODAY)
    assert (e["value_bp"], e["as_of"]) == (655, "2026-10-02")   # desordenadas: gana la más nueva
    assert e["unit"] == "pb" and e["country"] == "Argentina"


def test_an_observation_after_today_is_not_used():
    from analysis.fuentes import country_risk_entry

    obs = [(date(2026, 10, 1), 660.0), (date(2026, 10, 2), 655.0)]
    e = country_risk_entry(obs, today=date(2026, 10, 1))
    assert (e["value_bp"], e["as_of"]) == (660, "2026-10-01")


def test_the_entry_cites_the_chain_of_sources():
    from analysis.fuentes import country_risk_entry
    from config import FUENTES

    e = country_risk_entry([(date(2026, 10, 2), 655.0)], today=TODAY)
    assert e["source"] == FUENTES.country_risk_url
    assert "Ámbito" in e["note"] and "EMBI" in e["note"] and "J.P. Morgan" in e["note"]


# --------------------------------------------------------------------------- #
#  No es un rendimiento esperado: no entra al central                          #
# --------------------------------------------------------------------------- #

def _write(tmp_path, *, country_risk):
    path = tmp_path / "p.json"
    gestora = {"name": "G", "kind": "gestora", "asset_class": "emerging", "basis": "nominal",
               "currency": "USD", "as_of": "2026-06-30", "source": "https://example.org"}
    path.write_text(json.dumps({
        "entries": [{**gestora, "value_pct": 3.0}, {**gestora, "name": "H", "value_pct": 7.8}],
        "country_risk": country_risk,
    }), encoding="utf-8")
    return path


def test_the_country_risk_never_enters_the_emerging_central(tmp_path):
    from analysis.fuentes import load_country_risk, load_sources, summarize_class

    path = _write(tmp_path, country_risk=[{
        "country": "Argentina", "value_bp": 655, "unit": "pb", "as_of": "2026-10-02",
        "source": "https://example.org", "edition": "e", "note": "n",
    }])
    s = summarize_class("emerging", load_sources(path), today=TODAY)
    assert s.central_pct == pytest.approx(5.4)           # (3,0 + 7,8) / 2, sin el 655
    assert (s.low_pct, s.high_pct) == (3.0, 7.8)
    (cr,) = load_country_risk(path)
    assert (cr.country, cr.value_bp, cr.as_of) == ("Argentina", 655, date(2026, 10, 2))


def test_a_country_risk_in_another_unit_is_refused(tmp_path):
    from analysis.fuentes import load_country_risk

    path = _write(tmp_path, country_risk=[{
        "country": "Argentina", "value_bp": 6.55, "unit": "%", "as_of": "2026-10-02",
        "source": "https://example.org",
    }])
    with pytest.raises(ValueError, match="pb"):
        load_country_risk(path)


def test_the_shipped_file_carries_argentina_apart_from_the_entries():
    from analysis.fuentes import load_shipped, load_shipped_country_risk

    (cr,) = load_shipped_country_risk()
    assert cr.country == "Argentina" and cr.value_bp > 0 and cr.source.startswith("http")
    assert not [f for f in load_shipped() if "riesgo" in f.name.lower()]


# --------------------------------------------------------------------------- #
#  Antigüedad: las reglas de FUENTES (12 / 24 meses)                           #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("as_of, expected", [
    (date(2026, 10, 2), "vigente"),
    (date(2025, 9, 1), "vieja"),        # 13 meses
    (date(2024, 9, 1), "fuera"),        # 25 meses
])
def test_the_age_follows_the_fuentes_rules(as_of, expected):
    from analysis.fuentes import CountryRisk, country_risk_status

    cr = CountryRisk(country="Argentina", value_bp=655, as_of=as_of, source="https://x.org")
    assert country_risk_status(cr, today=TODAY) == expected


# --------------------------------------------------------------------------- #
#  Lo que ve el usuario                                                        #
# --------------------------------------------------------------------------- #

def test_the_optimizer_note_says_the_country_risk_is_in_the_return():
    from analysis.fuentes import CountryRisk
    from data.product_ux import ars_country_risk_note

    cr = CountryRisk(country="Argentina", value_bp=655, as_of=date(2026, 10, 2),
                     source="https://x.org")
    text = ars_country_risk_note("YPF, TEO", cr)
    assert "YPF, TEO" in text and "menos el riesgo país" in text and "0 % real" in text
    assert "655 pb" in text and "2026-10-02" in text and "Supuestos" in text
    assert "pendiente de Fuente" not in text
    # Sin el dato, el rótulo no inventa un número.
    assert "pb" not in ars_country_risk_note("YPF", None)


def test_the_score_discount_is_gone():
    from config import OPTIMIZER

    assert not hasattr(OPTIMIZER, "ars_risk_discount")
