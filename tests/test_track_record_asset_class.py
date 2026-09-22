"""``recommendation_log`` distingue la clase de activo de cada recomendación.

Sin esta columna, ``fundamental_score`` mezcla dos escalas incompatibles en el
mismo campo: la de equity llega a 100 y la de cripto a
``CRYPTO_MOAT.max_achievable_score()``. Agrupar por umbral sobre esa mezcla —que
es exactamente para lo que existe la tabla, ver ``StrategyConfig``— calibra contra
un promedio que no describe a ninguna de las dos clases.

Se agrega con la tabla en CERO filas (verificado el 2026-09-21 sobre la base real:
``recommendation_log`` y ``recommendation_outcome`` vacías), así que no hay nada
que backfillear ni que purgar. Es prevención: la clase no se puede reconstruir
una vez que el ticker cambió de sector o salió del universo, la misma razón por la
que las columnas de calibración de 2026-08 no podían esperar.

Migración aditiva, como todas las de este módulo. El módulo declara dos veces que
no borra, y esto no lo cambia.

Sin red y sin LLM.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from analysis.asset_class import CRYPTO, EQUITY
from analysis.track_record import (
    CALIBRATION_ATTRS,
    TrackRecordStore,
    calibration_fields,
    snapshot_calibration_inputs,
)


def _decision(symbol: str, action: str = "HOLD"):
    return SimpleNamespace(
        symbol=symbol, action=action, confidence="LOW",
        fundamental_score=40.0, technical_signal="BULLISH", rationale=["x"],
    )


def _crypto_fundamental():
    return SimpleNamespace(
        symbol="BTC-USD", asset_class=CRYPTO, is_crypto=True,
        sector="Crypto / Digital Asset", industry="Store of Value / Monetary Asset",
    )


def _equity_fundamental():
    return SimpleNamespace(
        symbol="MSFT", asset_class=EQUITY, is_crypto=False,
        sector="Technology", industry="Software",
        profitability_score=18.0, health_score=17.0,
    )


@pytest.fixture
def store(tmp_path):
    """Base propia por test — nunca la del usuario (CONTEXT §5)."""
    return TrackRecordStore(db_path=str(tmp_path / "tr.db"))


class TestLaClaseDeActivoSePersiste:
    def test_una_recomendacion_cripto_guarda_su_clase(self, store):
        rid = store.log_recommendation(
            _decision("BTC-USD"), source="committee", fundamental=_crypto_fundamental()
        )
        assert rid is not None
        rows = store.get_recommendations()
        assert rows[0].asset_class == CRYPTO

    def test_una_recomendacion_de_accion_guarda_la_suya(self, store):
        store.log_recommendation(
            _decision("MSFT", "BUY"), source="ai", fundamental=_equity_fundamental()
        )
        assert store.get_recommendations()[0].asset_class == EQUITY

    def test_sin_fundamental_la_fila_sigue_entrando(self, store):
        """La columna es opcional: nunca puede costar la recomendación entera."""
        assert store.log_recommendation(_decision("AAPL"), source="rule_based") is not None


class TestElFallbackCuandoAssetClassNoSeResolvio:
    def test_is_crypto_alcanza_aunque_asset_class_venga_vacio(self):
        """``asset_class`` es un default de dataclass; ``is_crypto`` lo fija
        ``CryptoAnalyzer`` en su primera línea, antes de cualquier fetch."""
        half_built = SimpleNamespace(asset_class="", is_crypto=True, sector="Crypto")
        assert calibration_fields(half_built)["asset_class"] == CRYPTO

    def test_una_accion_no_se_marca_como_cripto_por_accidente(self):
        half_built = SimpleNamespace(asset_class="", is_crypto=False, sector="Technology")
        assert "asset_class" not in calibration_fields(half_built)


class TestElRoundTripDelSnapshotSigueValiendo:
    """El contrato que ``snapshot_calibration_inputs`` documenta.

    El Screener arma filas dentro de un thread pool y no puede conservar el
    objeto, así que snapshotea los atributos crudos y reconstruye un stand-in.
    Si ``asset_class``/``is_crypto`` no viajaran en ``CALIBRATION_ATTRS``, el
    stand-in perdería la clase justo para el activo cuya escala de score es
    distinta — y nada fallaría, que es lo peor que podría pasar.
    """

    @pytest.mark.parametrize("build", [_crypto_fundamental, _equity_fundamental])
    def test_reconstruir_desde_el_snapshot_da_los_mismos_campos(self, build):
        fundamental = build()
        snapshot = snapshot_calibration_inputs(fundamental)
        assert calibration_fields(SimpleNamespace(**snapshot)) == calibration_fields(fundamental)

    def test_los_dos_atributos_viajan_en_el_snapshot(self):
        assert "asset_class" in CALIBRATION_ATTRS
        assert "is_crypto" in CALIBRATION_ATTRS


class TestLaMigracionEsAditiva:
    def test_una_base_vieja_sin_la_columna_se_migra_sin_perder_filas(self, tmp_path):
        import sqlite3

        path = tmp_path / "old.db"
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE recommendation_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, symbol VARCHAR NOT NULL, "
            "action VARCHAR NOT NULL, confidence VARCHAR, fundamental_score FLOAT, "
            "technical_signal VARCHAR, source VARCHAR, price_at_rec FLOAT, "
            "rationale TEXT, plan_id VARCHAR, created_at DATETIME)"
        )
        con.execute(
            "INSERT INTO recommendation_log (symbol, action, source) VALUES ('KO','BUY','ai')"
        )
        con.commit()
        con.close()

        store = TrackRecordStore(db_path=str(path))
        rows = store.get_recommendations()
        assert len(rows) == 1, "la migración perdió una fila preexistente"
        assert rows[0].symbol == "KO"
        assert rows[0].asset_class in ("", None), "una fila vieja no se inventa una clase"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
