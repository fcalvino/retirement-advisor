"""Oráculo — las 53 filas de fixture salen del track record en LECTURA (U5-18d).

N6 cortó la sangría: la suite ya no escribe. Quedaron **53 filas de 470** que sí
escribió, más **11 outcomes** puntuados sobre ellas. Esto las saca de lo que el
producto cuenta, sin borrar nada.

**Por qué no aplica el argumento de U5-18b.** Aquel decía: «el motor emitió esas
filas; que las haya emitido por un bug no las vuelve falsas, las vuelve el
registro de un bug». La palabra que carga el peso es *emitió*. Las 80 duplicadas
de U5-18b salieron de `full_analysis` sobre datos de mercado reales, en un
momento real, y el usuario pudo haberlas visto: el defecto era **contarlas dos
veces**, y colapsar en lectura arregla el conteo sin editar el hecho. Acá no hay
hecho. El `adjusted_score: 72.0` es un literal en `tests/test_alert_engine.py`,
la señal salió de un `store.seed(...)` y ningún precio se consultó —por eso las
53 tienen `price_at_rec` NULL—. El log de recomendaciones no es donde se
documenta un bug de testing; eso vive en git (PR #50).

**La regla que este archivo existe para defender: se enumeran los ids, nunca se
shipea el patrón.** Verificado el 2026-08-30 contra `main`:

  - El rationale `"Alerta de oportunidad: entró con señal …"` lo produce
    `alerts/engine.py:521` y `source="rule_based"` sale de `:528`. Los dos son
    **código de producción**: una corrida real del alert engine escribe una fila
    byte-idéntica en las tres columnas de la firma, `price_at_rec` NULL incluido
    (el loop de alertas no tiene precio, y el scorer lo resuelve en memoria sin
    persistirlo — `track_record_scorer.py:147`).
  - `source='rule_based'` tampoco es exclusivo del alert engine:
    `2_Stock_Analysis.py:180` lo escribe con la IA apagada.
  - La firma acierta 53/53 **hoy** por un accidente histórico, no por una regla:
    `alert_snapshots` tiene **0 filas**, y un arranque en frío guarda un baseline
    por ticker antes de poder disparar nada. El alert engine nunca completó una
    corrida real contra esta base, así que no hay ni una fila real de ese origen.
  - Y un `LIKE '%Alerta%'` **ya barrería una fila real**: la id 166 (CME,
    `source=screener`, `price_at_rec=278.63`), que lleva «Alerta» adentro de un
    rationale legítimo.

Un `WHERE` por patrón en el código se dispara solo el primer día que el scheduler
corra de verdad, sobre exactamente las filas que el path de alertas existe para
producir, y sin un error que lo avise. `test_the_decoy_row_survives` es el test
que falla si alguien cambia la lista por el patrón.

**Lo medido, que es lo que este archivo fija.** Los 22 outcomes a 30 días de la
base, el 2026-08-30, entran como literales en `MEASURED_OUTCOMES`:

                     n    acierto   exceso medio   equity modelo / benchmark
    publicado hoy   22     68,2 %       +6,29           2,572 / 1,124
    sólo reales     11     45,5 %       +3,21           0,913 / 1,031

La corrección no le baja el número al motor: **le da vuelta el signo**. El
producto muestra el modelo convirtiendo $1 en $2,57 contra un mercado que hizo
$1,12; el registro real es el modelo perdiendo 8,7 % mientras el mercado gana
3,1 %. Y las cuatro STRONG BUY puntuadas son **las cuatro fixtures**: sacadas,
no queda ninguna.

Sin red. Sin tocar la base del usuario (ver `conftest.py`).
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

from analysis.track_record import RecommendationLog, TrackRecordStore
from analysis.track_record_scorer import equity_curve, hit_rate_by_action, summary_stats

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts" / "mark_test_fixture_rows.py"


def _fixture_source() -> str:
    """``FIXTURE_SOURCE`` resuelto tarde, a propósito.

    Los tests de `TestTheDefectInNumbers` describen la base como está **hoy** y
    tienen que poder correr —y pasar— antes de que exista una línea del arreglo:
    son la medición del defecto, no del fix. Importarlo arriba haría que el
    archivo entero muriera en la colección y el commit rojo no probaría nada.
    """
    from analysis.track_record import FIXTURE_SOURCE

    return FIXTURE_SOURCE


def _load_migration():
    spec = importlib.util.spec_from_file_location("mark_test_fixture_rows", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ #
#  Lo medido: los 22 outcomes a 30 días, el 2026-08-30                 #
# ------------------------------------------------------------------ #

#: ``(rec_id, symbol, action, source, created_at, return_pct,
#:   benchmark_return_pct, excess_return_pct, hit, es_fixture)``
#: Copiados de `data/db/retirement_advisor.db` en read-only. Son literales a
#: propósito: el oráculo tiene que poder fallar aunque la base cambie, y ningún
#: test puede leer la base del usuario (CONTEXT §5).
MEASURED_OUTCOMES = [
    ( 1, "AAPL",    "HOLD",       "ai",         "2026-06-16 16:07:42",  11.6233,  0.3097,  11.3135, False, False),
    ( 2, "ABBV",    "HOLD",       "ai",         "2026-06-16 16:08:43",  14.0328,  0.3097,  13.7230, False, False),
    ( 3, "INTU",    "BUY",        "ai",         "2026-06-16 16:08:55",   4.7063,  0.3097,   4.3965, True,  False),
    ( 4, "MSFT",    "BUY",        "committee",  "2026-06-16 19:44:11",   1.6972,  0.3097,   1.3875, True,  False),
    ( 5, "INTU",    "HOLD",       "committee",  "2026-06-19 14:39:54",   9.0225, -0.4620,   9.4845, False, False),
    ( 6, "MSFT",    "BUY",        "committee",  "2026-06-19 14:52:42",   3.6057, -0.4620,   4.0677, True,  False),
    ( 7, "AAPL",    "BUY",        "rule_based", "2026-06-19 22:07:52",  11.9895, -0.4620,  12.4515, True,  True),
    ( 8, "XOM",     "STRONG BUY", "rule_based", "2026-06-19 22:07:52",   6.9298, -0.4620,   7.3918, True,  True),
    ( 9, "AAPL",    "BUY",        "rule_based", "2026-06-21 13:52:12",   9.9762,  0.2062,   9.7699, True,  True),
    (10, "MSFT",    "BUY",        "rule_based", "2026-06-21 13:52:12",   4.8366,  0.2062,   4.6303, True,  True),
    (11, "XOM",     "STRONG BUY", "rule_based", "2026-06-21 13:52:12",  10.0864,  0.2062,   9.8801, True,  True),
    (12, "INTU",    "BUY",        "ai",         "2026-06-23 11:43:38",   9.2175,  0.6271,   8.5905, True,  False),
    (13, "INTU",    "HOLD",       "committee",  "2026-06-23 11:44:28",   9.2175,  0.6271,   8.5905, False, False),
    (14, "AAPL",    "BUY",        "rule_based", "2026-06-23 16:05:18",   9.2966,  0.6271,   8.6696, True,  True),
    (15, "MSFT",    "BUY",        "rule_based", "2026-06-23 16:05:18",   2.0431,  0.6271,   1.4160, True,  True),
    (16, "XOM",     "STRONG BUY", "rule_based", "2026-06-23 16:05:18",  12.2808,  0.6271,  11.6538, True,  True),
    (17, "QCOM",    "BUY",        "committee",  "2026-06-23 19:45:43", -22.8887,  0.6271, -23.5157, False, False),
    (18, "CEPU",    "BUY",        "ai",         "2026-06-28 21:03:41",  -1.6915,  1.6283,  -3.3198, False, False),
    (19, "BTC-USD", "HOLD",       "ai",         "2026-07-09 14:50:44",   3.4970,  2.8668,   0.6302, True,  False),
    (20, "AAPL",    "BUY",        "rule_based", "2026-07-11 17:32:09",  -2.1547,  2.3949,  -4.5495, False, True),
    (21, "MSFT",    "BUY",        "rule_based", "2026-07-11 17:32:09",  31.4100,  2.3949,  29.0152, True,  True),
    (22, "XOM",     "STRONG BUY", "rule_based", "2026-07-11 17:32:09",  15.0562,  2.3949,  12.6613, True,  True),
]


def _as_rows(records) -> list[dict]:
    """La forma que devuelve ``get_scored_rows``."""
    return [
        {
            "rec_id": rec_id,
            "symbol": symbol,
            "action": action,
            "confidence": "MEDIUM",
            "source": source,
            "created_at": datetime.fromisoformat(created_at),
            "price_at_rec": None,
            "horizon_days": 30,
            "return_pct": ret,
            "benchmark_return_pct": bench,
            "excess_return_pct": excess,
            "hit": hit,
            "benchmark_missing": False,
        }
        for rec_id, symbol, action, source, created_at, ret, bench, excess, hit, _fx in records
    ]


PUBLISHED = _as_rows(MEASURED_OUTCOMES)
REAL_ONLY = _as_rows([r for r in MEASURED_OUTCOMES if not r[-1]])


class TestTheDefectInNumbers:
    """Lo que el producto publica hoy contra lo que el motor realmente hizo."""

    def test_published_headline_is_the_contaminated_one(self):
        stats = summary_stats(PUBLISHED)
        assert stats["n"] == 22
        assert stats["overall_hit_rate"] == pytest.approx(0.6818, abs=1e-4)
        assert stats["mean_excess_pct"] == pytest.approx(6.2881, abs=1e-3)

    def test_real_headline_is_twenty_two_points_lower(self):
        stats = summary_stats(REAL_ONLY)
        assert stats["n"] == 11
        assert stats["overall_hit_rate"] == pytest.approx(0.4545, abs=1e-4)
        assert stats["mean_excess_pct"] == pytest.approx(3.2135, abs=1e-3)
        # +22,7 pp inflados a favor del motor.
        inflado = summary_stats(PUBLISHED)["overall_hit_rate"] - stats["overall_hit_rate"]
        assert inflado == pytest.approx(0.2273, abs=1e-3)

    def test_the_equity_curve_flips_sign(self):
        """El número que decide: no es que el motor rinda menos, es que pierde."""
        pub = equity_curve(PUBLISHED)
        real = equity_curve(REAL_ONLY)

        assert float(pub["model_equity"].iloc[-1]) == pytest.approx(2.5719, abs=1e-3)
        assert float(pub["benchmark_equity"].iloc[-1]) == pytest.approx(1.1240, abs=1e-3)
        assert float(real["model_equity"].iloc[-1]) == pytest.approx(0.9134, abs=1e-3)
        assert float(real["benchmark_equity"].iloc[-1]) == pytest.approx(1.0307, abs=1e-3)

        # Publicado: el modelo le gana 2,3× al mercado. Real: le pierde.
        assert float(pub["model_equity"].iloc[-1]) > float(pub["benchmark_equity"].iloc[-1])
        assert float(real["model_equity"].iloc[-1]) < float(real["benchmark_equity"].iloc[-1])
        assert float(real["model_equity"].iloc[-1]) < 1.0  # el modelo pierde plata

    def test_every_scored_strong_buy_is_a_fixture(self):
        """La fila que el producto presenta como concluyente (100 %, `inconclusive=False`)."""
        pub = hit_rate_by_action(PUBLISHED)
        assert pub["STRONG BUY"]["n"] == 4
        assert pub["STRONG BUY"]["hit_rate"] == 1.0
        assert pub["STRONG BUY"]["inconclusive"] is False

        # Sacadas las fixtures no queda ninguna: no hay muestra de STRONG BUY.
        assert "STRONG BUY" not in hit_rate_by_action(REAL_ONLY)

    def test_buy_excess_flips_sign_too(self):
        assert hit_rate_by_action(PUBLISHED)["BUY"]["mean_excess_pct"] == pytest.approx(4.0777, abs=1e-3)
        assert hit_rate_by_action(REAL_ONLY)["BUY"]["mean_excess_pct"] == pytest.approx(-1.3989, abs=1e-3)


# ------------------------------------------------------------------ #
#  La exclusión, en los tres sitios de query                           #
# ------------------------------------------------------------------ #

def _seed_store() -> TrackRecordStore:
    """Store en memoria con una fila real y una marcada como fixture.

    Las dos son viejas (60 días) para que `get_pending_scoring` las considere, y
    ninguna tiene outcome.
    """
    store = TrackRecordStore(":memory:")
    old = datetime(2026, 6, 1, 12, 0, 0)
    with store._Session() as s:
        s.add(RecommendationLog(
            id=1, symbol="INTU", action="BUY", source="ai",
            price_at_rec=100.0, rationale="[]", created_at=old,
        ))
        s.add(RecommendationLog(
            id=2, symbol="XOM", action="STRONG BUY", source=_fixture_source(),
            price_at_rec=None,
            rationale='["Alerta de oportunidad: entró con señal STRONG_BUY"]',
            created_at=old,
        ))
        s.commit()
    return store


class TestTheThreeQuerySites:
    def test_get_recommendations_excludes_fixtures(self):
        """Sin esto el titular «Recomendaciones logueadas» sigue diciendo 470."""
        store = _seed_store()
        assert [r.id for r in store.get_recommendations()] == [1]
        assert sorted(r.id for r in store.get_recommendations(include_fixtures=True)) == [1, 2]

    def test_get_pending_scoring_excludes_fixtures(self):
        """El sitio urgente: es lo que impide que las 42 restantes se puntúen."""
        store = _seed_store()
        now = datetime(2026, 8, 30, 12, 0, 0)
        assert [r.id for r in store.get_pending_scoring(30, now=now)] == [1]
        assert sorted(r.id for r in store.get_pending_scoring(30, now=now, include_fixtures=True)) == [1, 2]

    def test_get_scored_rows_excludes_fixtures(self):
        store = _seed_store()
        for rec_id in (1, 2):
            store.save_outcome(
                rec_id=rec_id, horizon_days=30, price_at_horizon=110.0,
                return_pct=10.0, benchmark_return_pct=1.0, excess_return_pct=9.0, hit=True,
            )
        assert [r["rec_id"] for r in store.get_scored_rows(30)] == [1]
        assert sorted(r["rec_id"] for r in store.get_scored_rows(30, include_fixtures=True)) == [1, 2]

    def test_the_fixture_source_never_reaches_the_page_source_filter(self):
        """La página arma el multiselect «Fuente» con los `source` que ve."""
        store = _seed_store()
        store.save_outcome(rec_id=2, horizon_days=30, price_at_horizon=1.0,
                           return_pct=1.0, benchmark_return_pct=1.0,
                           excess_return_pct=0.0, hit=True)
        fuentes = {r["source"] for r in store.get_scored_rows(30)}
        assert _fixture_source() not in fuentes

    def test_exclusion_is_orthogonal_to_the_collapse(self):
        """Dos preguntas distintas, dos flags. No se fusionan (pecado de U5-18)."""
        store = _seed_store()
        store.save_outcome(rec_id=2, horizon_days=30, price_at_horizon=1.0,
                           return_pct=1.0, benchmark_return_pct=1.0,
                           excess_return_pct=0.0, hit=True)
        # Apagar el collapse no puede devolver las fixtures.
        assert store.get_scored_rows(30, collapse_same_day=False) == []
        # Y pedir las fixtures no puede depender del collapse.
        crudo = store.get_scored_rows(30, collapse_same_day=False, include_fixtures=True)
        assert [r["rec_id"] for r in crudo] == [2]


class TestTheOutcomesFallOutWithTheirRow:
    def test_an_outcome_without_a_visible_row_is_dropped(self):
        """Los 11 outcomes no se borran ni se marcan: caen por el join."""
        store = _seed_store()
        store.save_outcome(rec_id=2, horizon_days=30, price_at_horizon=1.0,
                           return_pct=5.0, benchmark_return_pct=1.0,
                           excess_return_pct=4.0, hit=True)
        assert store.get_scored_rows(30) == []

    def test_the_outcome_row_itself_is_untouched(self):
        """El precio explícito: un COUNT sobre la tabla de outcomes no cambia.

        Por eso toda lectura tiene que joinear — el que consulte
        `recommendation_outcome` directo sigue viendo el número contaminado.
        """
        from analysis.track_record import RecommendationOutcome

        store = _seed_store()
        store.save_outcome(rec_id=2, horizon_days=30, price_at_horizon=1.0,
                           return_pct=5.0, benchmark_return_pct=1.0,
                           excess_return_pct=4.0, hit=True)
        with store._Session() as s:
            assert s.query(RecommendationOutcome).count() == 1


# ------------------------------------------------------------------ #
#  La regla: ids enumerados, nunca el patrón                           #
# ------------------------------------------------------------------ #

#: Los 53 ids, derivados el 2026-08-30 contra la base congelada. Duplicados acá a
#: propósito: si el script cambia su lista sin que nadie lo note, este test lo ve.
EXPECTED_IDS = (
    7, 8, 9, 10, 11, 14, 15, 16, 20, 21, 22, 24, 25, 26, 36, 37, 38, 39, 40, 41,
    43, 44, 45, 47, 48, 49, 52, 53, 54, 55, 56, 57, 137, 138, 139, 140, 141, 142,
    143, 144, 145, 223, 224, 225, 303, 304, 305, 395, 396, 397, 468, 469, 470,
)


class TestTheIdentificationRule:
    def test_the_migration_ships_a_literal_id_list(self):
        mig = _load_migration()
        assert tuple(mig.FIXTURE_ROW_IDS) == EXPECTED_IDS
        assert len(set(mig.FIXTURE_ROW_IDS)) == 53
        assert all(isinstance(i, int) for i in mig.FIXTURE_ROW_IDS)
        # El conjunto está cerrado: la última fixture es la 470 y desde PR #50 la
        # suite no puede escribir más.
        assert max(mig.FIXTURE_ROW_IDS) == 470

    def test_the_migration_never_selects_by_pattern(self):
        """Barrido del fuente: ni un LIKE, ni el rationale como criterio."""
        fuente = MIGRATION.read_text(encoding="utf-8")
        # Sólo la parte ejecutable: los comentarios explican justamente por qué no.
        codigo = "\n".join(
            linea for linea in fuente.splitlines()
            if not linea.lstrip().startswith("#")
        )
        for prohibido in ("like(", "LIKE", "ilike(", "contains("):
            assert prohibido not in codigo, f"el script selecciona por patrón: {prohibido}"

    def test_the_decoy_row_survives(self):
        """El test que rompe si alguien cambia la lista por el patrón.

        El señuelo es una corrida **real** del alert engine: rationale y `source`
        byte-idénticos a los de las fixtures, `price_at_rec` NULL, uno de los tres
        símbolos. No está en la lista de ids, así que no se toca. Y la segunda es
        la forma de la id 166 (CME), que un `LIKE '%Alerta%'` barrería.
        """
        mig = _load_migration()
        store = TrackRecordStore(":memory:")
        with store._Session() as s:
            for row_id in mig.FIXTURE_ROW_IDS:
                s.add(RecommendationLog(
                    id=row_id, symbol="XOM", action="STRONG BUY", source="rule_based",
                    price_at_rec=None,
                    rationale='["Alerta de oportunidad: entró con señal STRONG_BUY"]',
                    created_at=datetime(2026, 6, 21, 13, 52, 12),
                ))
            # Señuelo 1 — corrida real del alert engine, firma idéntica.
            s.add(RecommendationLog(
                id=9001, symbol="XOM", action="STRONG BUY", source="rule_based",
                price_at_rec=None,
                rationale='["Alerta de oportunidad: entró con señal STRONG_BUY"]',
                created_at=datetime(2026, 9, 15, 10, 0, 0),
            ))
            # Señuelo 2 — la id 166 real: «Alerta» adentro de un rationale legítimo.
            s.add(RecommendationLog(
                id=9002, symbol="CME", action="STRONG BUY", source="screener",
                price_at_rec=278.63,
                rationale='["Moat Wide…", "Alerta: la valuación exige crecimiento"]',
                created_at=datetime(2026, 8, 25, 14, 37, 25),
            ))
            s.commit()

        report = mig.mark_fixture_rows(store, dry_run=False)
        assert report["marked"] == 53

        with store._Session() as s:
            decoy = s.get(RecommendationLog, 9001)
            cme = s.get(RecommendationLog, 9002)
            assert decoy.source == "rule_based", "se barrió una corrida real del alert engine"
            assert cme.source == "screener", "se barrió la fila real que lleva «Alerta»"
            marcadas = {
                r.id for r in s.query(RecommendationLog)
                .filter(RecommendationLog.source == _fixture_source()).all()
            }
        assert marcadas == set(EXPECTED_IDS)

    def test_dry_run_is_the_default_and_writes_nothing(self):
        mig = _load_migration()
        store = TrackRecordStore(":memory:")
        with store._Session() as s:
            s.add(RecommendationLog(
                id=7, symbol="AAPL", action="BUY", source="rule_based",
                price_at_rec=None, rationale="[]", created_at=datetime(2026, 6, 19, 22, 7, 52),
            ))
            s.commit()

        report = mig.mark_fixture_rows(store)  # sin argumentos: dry-run
        assert report["dry_run"] is True
        with store._Session() as s:
            assert s.get(RecommendationLog, 7).source == "rule_based"

    def test_marking_is_idempotent(self):
        mig = _load_migration()
        store = TrackRecordStore(":memory:")
        with store._Session() as s:
            for row_id in mig.FIXTURE_ROW_IDS:
                s.add(RecommendationLog(
                    id=row_id, symbol="AAPL", action="BUY", source="rule_based",
                    price_at_rec=None, rationale="[]", created_at=datetime(2026, 6, 19, 22, 7, 52),
                ))
            s.commit()

        first = mig.mark_fixture_rows(store, dry_run=False)
        second = mig.mark_fixture_rows(store, dry_run=False)
        assert first["marked"] == 53 and first["already_marked"] == 0
        assert second["marked"] == 0 and second["already_marked"] == 53

    def test_an_unexpected_source_aborts_without_writing(self):
        """El guard que protege del error serio: marcar una fila real.

        Si un id de la lista no tiene hoy `source='rule_based'`, la lista está
        mal o la base cambió — y en los dos casos hay que parar, no escribir.
        """
        mig = _load_migration()
        store = TrackRecordStore(":memory:")
        with store._Session() as s:
            for row_id in mig.FIXTURE_ROW_IDS:
                fuente = "screener" if row_id == 145 else "rule_based"
                s.add(RecommendationLog(
                    id=row_id, symbol="AAPL", action="BUY", source=fuente,
                    price_at_rec=None, rationale="[]", created_at=datetime(2026, 6, 19, 22, 7, 52),
                ))
            s.commit()

        with pytest.raises(mig.UnexpectedRowError):
            mig.mark_fixture_rows(store, dry_run=False)

        with store._Session() as s:
            intactas = s.query(RecommendationLog).filter(
                RecommendationLog.source == _fixture_source()
            ).count()
        assert intactas == 0, "abortó pero igual escribió"

    def test_the_preview_shows_what_a_human_needs_to_review_it(self):
        """Se revisa fila por fila antes de aplicar: id, símbolo, acción, fecha,
        source actual y si tiene outcome."""
        mig = _load_migration()
        store = _seed_store()
        with store._Session() as s:
            s.query(RecommendationLog).filter(RecommendationLog.id == 2).update(
                {"source": "rule_based"}
            )
            s.commit()
        store.save_outcome(rec_id=2, horizon_days=30, price_at_horizon=1.0,
                           return_pct=1.0, benchmark_return_pct=1.0,
                           excess_return_pct=0.0, hit=True)

        filas = mig.preview(store, ids=(2,))
        assert len(filas) == 1
        fila = filas[0]
        for campo in ("id", "symbol", "action", "created_at", "source", "has_outcome"):
            assert campo in fila, f"la preview no muestra {campo}"
        assert fila["has_outcome"] is True
        assert fila["source"] == "rule_based"

    def test_a_missing_id_is_reported_not_skipped(self):
        """Una base sin esa fila no es «nada que hacer»: es una discrepancia."""
        mig = _load_migration()
        store = TrackRecordStore(":memory:")
        with store._Session() as s:
            for row_id in mig.FIXTURE_ROW_IDS[:-1]:
                s.add(RecommendationLog(
                    id=row_id, symbol="AAPL", action="BUY", source="rule_based",
                    price_at_rec=None, rationale="[]", created_at=datetime(2026, 6, 19, 22, 7, 52),
                ))
            s.commit()

        report = mig.mark_fixture_rows(store, dry_run=True)
        assert report["missing"] == [470]
