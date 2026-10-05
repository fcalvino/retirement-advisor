"""Oráculo EO-2c: el riesgo país de Argentina como dato fechado y citado (ADR 0001).

Decisiones del usuario (2026-10-05):
- Entra como dato, no como rendimiento esperado: no toca la mediana ni el
  Desacuerdo de emergentes. ``OPTIMIZER.ars_risk_discount`` (0,85) sigue igual,
  rotulado «pendiente de Fuente»; convertir el riesgo país en la Estimación de un
  ADR argentino es de EO-4.
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

def test_the_optimizer_note_keeps_the_discount_pending_and_points_to_supuestos():
    from analysis.fuentes import CountryRisk
    from data.product_ux import ars_discount_note

    cr = CountryRisk(country="Argentina", value_bp=655, as_of=date(2026, 10, 2),
                     source="https://x.org")
    text = ars_discount_note(0.85, "YPF, TEO", cr)
    assert "**15%**" in text                                   # (1 − 0,85) × 100
    assert "pendiente de Fuente" in text and "Supuestos" in text and "EO-4" in text
    assert "655 pb" in text and "2026-10-02" in text
    # Sin el dato, el rótulo no inventa un número.
    assert "pb" not in ars_discount_note(0.85, "YPF", None)


def test_the_discount_itself_does_not_move():
    from config import OPTIMIZER

    assert OPTIMIZER.ars_risk_discount == 0.85
    assert "conservative/moderate" not in (type(OPTIMIZER).__doc__ or "")


def test_the_supuestos_page_shows_the_country_risk_outside_the_central(monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import analysis.fuentes as fuentes_mod

    def f(v, name):
        return fuentes_mod.Fuente(name=name, kind="gestora", asset_class="emerging",
                                  value_pct=v, basis="nominal", currency="USD",
                                  as_of=date(2026, 6, 30), source="https://example.org")

    cr = fuentes_mod.CountryRisk(country="Argentina", value_bp=655, as_of=date(2026, 10, 2),
                                 source="https://example.org")
    monkeypatch.setattr(fuentes_mod, "load_shipped", lambda: [f(3.0, "G"), f(7.8, "H")])
    monkeypatch.setattr(fuentes_mod, "load_shipped_country_risk", lambda: [cr])
    monkeypatch.setattr(fuentes_mod, "today", lambda: TODAY)
    page = Path(__file__).resolve().parents[1] / "dashboard/views/21_Supuestos.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    text = "\n".join((getattr(e, "value", "") or "") for coll in (
        at.markdown, at.caption, at.info, at.warning) for e in coll)
    assert "Central 5.4%" in text and "3.0%–7.8%" in text
    assert "655 pb" in text and "no entra al central" in text
