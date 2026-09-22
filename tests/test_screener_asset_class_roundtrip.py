"""El Screener sigue intacto después de la serie cripto del comité (PR 1–4).

Los PR 1–4 tocaron tres cosas que el Screener comparte con el comité y que nadie
ejercitaba juntas: la firma de ``cached_full_analysis`` (nuevo ``ai_enrich_only``,
que además entra en la clave de caché), la columna ``asset_class`` de
``recommendation_log``, y el par ``asset_class``/``is_crypto`` dentro de
``CALIBRATION_ATTRS``.

El Screener es la superficie de más riesgo justamente porque **no** fue tocada: es
el mayor productor de filas del track record (una por ticker por corrida, ~149),
arma esas filas dentro de un thread pool y las persiste como JSON en
``data/screener_last_run.json``, así que sus payloads **sobreviven al upgrade**.
Una corrida guardada antes de PR 4 se vuelve a loguear después, con ``inputs`` que
no traen ni ``asset_class`` ni ``is_crypto``: ése es el caso de "fila vieja" que
importa, y el modo de falla que hay que excluir es el silencioso — que invente una
clase, o que se pierda la del activo cuya escala de score es distinta.

``tests/test_track_record_asset_class.py`` cubre la columna y la migración en el
store. Esto cubre el **camino del Screener** hasta la columna, que es otro tramo.

Sin red y sin LLM.
"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest

from analysis.asset_class import CRYPTO, EQUITY
from analysis.track_record import (
    TrackRecordStore,
    calibration_fields,
    snapshot_calibration_inputs,
)
from dashboard.shared import _track_payload, cached_full_analysis, log_screener_run


def _equity(symbol="O"):
    return SimpleNamespace(
        symbol=symbol, company_name="Test Co",
        sector="Real Estate", industry="REIT - Retail",
        asset_class=EQUITY, is_crypto=False,
        current_price=57.0, adjusted_score=68.0,
        profitability_score=12.0, health_score=6.0, valuation_score=8.0,
        growth_score=10.0, dividend_score=9.0,
        p_ffo=16.5, roe=8.4, roic=5.1, moat_score=11.0,
    )


def _crypto():
    return SimpleNamespace(
        symbol="BTC-USD", company_name="Bitcoin",
        sector="Crypto / Digital Asset", industry="Store of Value / Monetary Asset",
        asset_class=CRYPTO, is_crypto=True,
        current_price=87000.0, adjusted_score=40.5,
    )


def _decision(symbol="O", action="BUY"):
    return SimpleNamespace(
        symbol=symbol, action=action, confidence="HIGH",
        fundamental_score=68.0, technical_signal="BULLISH",
        rationale=["uno", "dos"],
    )


def _row(fund, decision):
    return {"Ticker": fund.symbol, "_track": _track_payload(fund, decision)}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Base propia — nunca la del usuario (CONTEXT §5)."""
    s = TrackRecordStore(db_path=str(tmp_path / "screener.db"))
    monkeypatch.setattr("analysis.track_record.track_record_store", s)
    return s


class TestElScreenerNoPideEnriquecimiento:
    """``ai_enrich_only`` es del comité, y el Screener no puede heredarlo.

    Si el Screener enriqueciera, cada corrida se llevaría una llamada de moat por
    ticker contra el mismo presupuesto TPM de Groq que la corrida necesita — y
    ``1_Screener.py`` deriva el badge de IA de ``enrich_only``, así que la fila
    guardada diría ``ai_used=False`` sobre una corrida que sí llamó al proveedor.
    """

    def test_el_parametro_existe_y_es_opcional_y_apagado(self):
        params = inspect.signature(cached_full_analysis).parameters
        assert "ai_enrich_only" in params
        assert params["ai_enrich_only"].default is False

    def test_el_screener_lo_deja_en_su_default(self):
        src = inspect.getsource(
            __import__("dashboard.shared", fromlist=["x"])
        )
        for fn in ("_analyse_universe_parallel", "_fetch_universe_parallel"):
            block = src[src.index(f"def {fn}") :]
            end = block.find("\ndef ", 1)  # -1 cuando la función cierra el módulo
            block = block if end < 0 else block[:end]
            assert "cached_full_analysis(" in block, f"{fn} dejó de analizar"
            assert "enrich_only" not in block, (
                f"{fn} pasa enrich_only: el Screener no debe enriquecer"
            )


class TestLaClaseLlegaDesdeElScreenerHastaLaColumna:
    def test_una_accion_queda_marcada_como_equity(self, store):
        assert log_screener_run([_row(_equity(), _decision())]) == 1
        assert store.get_recommendations(limit=1)[0].asset_class == EQUITY

    def test_un_cripto_sigue_sin_entrar_por_el_screener(self, store):
        """El filtro de scorabilidad es anterior a PR 4 y tiene que seguir ahí:
        la escala cripto nunca debe mezclarse en ``fundamental_score``."""
        rows = [_row(_crypto(), _decision("BTC-USD", "HOLD")), _row(_equity(), _decision())]
        assert log_screener_run(rows) == 1
        assert store.get_recommendations(limit=10)[0].symbol == "O"


class TestUnaCorridaGuardadaAntesDelCambio:
    """El payload vive en disco como JSON y se vuelve a loguear tras el upgrade."""

    @staticmethod
    def _payload_viejo():
        payload = _track_payload(_equity(), _decision())
        payload["inputs"].pop("asset_class", None)
        payload["inputs"].pop("is_crypto", None)
        return {"Ticker": "O", "_track": json.loads(json.dumps(payload))}

    def test_la_fila_vieja_se_loguea_igual(self, store):
        assert log_screener_run([self._payload_viejo()]) == 1

    def test_y_no_se_inventa_una_clase(self, store):
        log_screener_run([self._payload_viejo()])
        rec = store.get_recommendations(limit=1)[0]
        assert rec.asset_class in ("", None), "una corrida vieja no puede inventar la clase"
        assert rec.sector == "Real Estate", "el resto de la calibración tiene que sobrevivir"


class TestElRoundTripPorDiscoDelScreener:
    """``snapshot_calibration_inputs`` → JSON → stand-in → ``calibration_fields``.

    El tramo por JSON es el que el Screener usa de verdad y el que
    ``test_track_record_asset_class.py`` no recorre: ahí el round-trip se hace en
    memoria. Un ``bool`` sobrevive a ``json``; el test lo fija para que agregar un
    atributo no serializable a ``CALIBRATION_ATTRS`` falle acá y no en producción.
    """

    @pytest.mark.parametrize("build", [_equity, _crypto])
    def test_la_clase_sobrevive_al_viaje_por_json(self, build):
        fundamental = build()
        rebuilt = SimpleNamespace(
            **json.loads(json.dumps(snapshot_calibration_inputs(fundamental)))
        )
        assert calibration_fields(rebuilt) == calibration_fields(fundamental)

    def test_el_payload_entero_es_json_serializable(self):
        for build, dec in ((_equity, _decision()), (_crypto, _decision("BTC-USD", "HOLD"))):
            json.dumps(_track_payload(build(), dec))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
