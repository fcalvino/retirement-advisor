"""Oráculo — deduplicar el track record en LECTURA, no borrando filas.

U5-18 arregló el **día del dedup** en la escritura: `_exists_today` cortaba a las
00:00 UTC, así que para un usuario en UTC−3 el "día" corría de 21:00 a 21:00
local. El arreglo no migró nada, y no podía: las filas que la regla vieja dejó
entrar siguen ahí. Medido sobre `recommendation_log` el 2026-08-30:

    467 filas | dup por día LOCAL: 80 | sobreviven al corte local: 387 (17,1 %)

    tramo pre-fix (día local < 2026-08-29, 386 filas, congelado)
        dup por día UTC:    0
        dup por día LOCAL: 80   → sobreviven 306, el 20,7 %
    tramo post-fix (81 filas)
        dup por día UTC:    0
        dup por día LOCAL:  0

**Por qué en lectura y no borrando.** El impacto de hoy es exactamente cero —las
cinco métricas dan idénticas con y sin collapse— y es cero por una razón
estructural, no por suerte: `get_scored_rows` itera `recommendation_outcome`, y
ninguna duplicada tiene outcome porque ninguna cumplió 30 días. Las 22 scoreadas
son los `rec_id` 1–22, las únicas con más de 30 días de antigüedad. O sea que
borrar no arreglaría ningún número de hoy, y sí destruiría —la base está
gitignoreada— el único registro de que el defecto de U5-18 existió y de qué
tamaño fue.

**El efecto grave no es la inflación de `n`.** Esa existe (las bandas de
`mean_with_band` saldrían 8–12 % más angostas por el 1/√n), pero es de segundo
orden. El grave es que **`equity_curve` compone**: cada fila multiplica el
capital, así que una duplicada aplica dos veces el mismo retorno. Y el sesgo es
asimétrico y a favor del motor, porque el modelo compone más rápido que el
benchmark: proyectado sobre la curva real, `model_equity` queda +17,5 %
sobrestimado contra +2,0 % del benchmark, y la brecha que el gráfico exhibe como
mérito propio se ensancha sola. Es el mismo defecto que U2-4 cerró por otra
puerta —dejar que el modelo compusiera contra una línea plana—.

Los cuatro contratos que fija este archivo:

  1. La clave de lectura es **literalmente** la del write-side. No se compara
     texto: se ejercitan `_exists_today` y `collapse_same_local_day` con los
     mismos datos, en cuatro zonas horarias, y se exige que coincidan.
  2. Sobrevive la **primera** del día local. Es la que `_exists_today` ya elige
     (rechaza la posterior), así que quedarse con la última mezclaría dos
     políticas de selección en la misma muestra — que es la clase de defecto que
     U5-18 cerró.
  3. El default está **prendido**, para que los dos consumidores se corrijan sin
     tocarse.
  4. El flag apagado es la puerta para auditar el crudo — justo lo que borrar
     las filas sacaría para siempre.

Sin red, sin Streamlit.
"""

from __future__ import annotations

import ast
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from analysis.track_record import (
    RecommendationLog,
    TrackRecordStore,
    collapse_same_local_day,
    same_local_day_key,
)
from analysis.track_record_scorer import (
    calibration_by_confidence,
    equity_curve,
    hit_rate_by_action,
    hit_rate_by_source,
    summary_stats,
)
from data.clock import local_day_start_utc

ROOT = Path(__file__).resolve().parents[1]


#: Las mismas cuatro zonas que `test_clock_oracle.py`. La lista existe porque un
#: verde que depende de dónde se corre no es evidencia: UTC está adentro a
#: propósito (es donde corre el CI y donde el corte local y el UTC coinciden), y
#: Kolkata también, que es el offset de media hora que rompe los atajos.
ZONAS = [
    ("America/Argentina/Buenos_Aires", -3),
    ("Asia/Tokyo", +9),
    ("UTC", 0),
    ("Asia/Kolkata", +5.5),
]


@pytest.fixture
def zona():
    """Fija la zona horaria del proceso y la restaura después."""
    previa = os.environ.get("TZ")

    def _set(nombre: str):
        os.environ["TZ"] = nombre
        time.tzset()

    yield _set
    if previa is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previa
    time.tzset()


@pytest.fixture
def store():
    return TrackRecordStore(db_path=":memory:")


# --------------------------------------------------------------------------- #
#  Helpers: filas crudas, con la fecha que queremos                            #
# --------------------------------------------------------------------------- #

def _insert(store, *, symbol, action, when, source="screener",
            confidence="MEDIUM", price=100.0) -> int:
    """Escribe una fila del log salteando el dedup del write-side.

    Tiene que saltearlo: las 80 duplicadas reales son justamente las que la regla
    vieja dejó entrar, y no hay forma de reproducirlas pasando por la regla nueva.
    """
    with store._Session() as s:  # noqa: SLF001 - test introspection
        row = RecommendationLog(
            symbol=symbol.upper(), action=action, confidence=confidence,
            source=source, price_at_rec=price, created_at=when,
        )
        s.add(row)
        s.commit()
        return row.id


def _score(store, rec_id, *, return_pct, benchmark_return_pct, hit, horizon=30):
    store.save_outcome(
        rec_id=rec_id, horizon_days=horizon, price_at_horizon=100.0,
        return_pct=return_pct, benchmark_return_pct=benchmark_return_pct,
        excess_return_pct=return_pct - benchmark_return_pct, hit=hit,
    )


def _cinco_metricas(rows) -> dict:
    """Las cinco que lee la página. El `equity_curve` se serializa para comparar."""
    eq = equity_curve(rows)
    return {
        "summary": summary_stats(rows),
        "calibration": calibration_by_confidence(rows),
        "by_action": hit_rate_by_action(rows),
        "by_source": hit_rate_by_source(rows),
        "equity": [] if eq.empty else eq.to_dict("records"),
    }


def _dos_del_mismo_dia_local(dia_ancla: datetime) -> tuple[datetime, datetime]:
    """Dos instantes UTC del mismo día **local**, a distinto lado del día UTC.

    Se construyen desde la medianoche local —no sumando horas a una fecha UTC—
    porque es la única forma de que la propiedad valga en las cuatro zonas.
    """
    medianoche = local_day_start_utc(dia_ancla)
    return medianoche + timedelta(hours=9), medianoche + timedelta(hours=22)


# --------------------------------------------------------------------------- #
#  1. Hoy es un no-op — y por una razón estructural, no por suerte             #
# --------------------------------------------------------------------------- #

class TestHoyNoMueveNingunNumero:
    """La forma real de la base: hay duplicadas, pero ninguna llegó a los 30 días."""

    def test_las_cinco_metricas_son_identicas_con_y_sin_collapse(self, store, zona):
        zona("America/Argentina/Buenos_Aires")
        ahora = datetime(2026, 8, 30, 12, 0, 0)

        # Las que sí tienen outcome: viejas y sin repetir (los rec_id 1–22).
        for i, (sym, act, ret) in enumerate([
            ("AAPL", "BUY", 8.0), ("MSFT", "BUY", 3.0),
            ("XOM", "STRONG BUY", 12.0), ("KO", "HOLD", 1.0),
        ]):
            rid = _insert(store, symbol=sym, action=act, when=ahora - timedelta(days=60 + i))
            _score(store, rid, return_pct=ret, benchmark_return_pct=2.0, hit=ret > 2.0)

        # Las duplicadas: recientes, dentro de su horizonte, sin outcome.
        primera, segunda = _dos_del_mismo_dia_local(ahora - timedelta(days=2))
        for sym in ("NVDA", "AMD", "INTC"):
            _insert(store, symbol=sym, action="BUY", when=primera)
            _insert(store, symbol=sym, action="BUY", when=segunda)

        crudo = store.get_scored_rows(30, collapse_same_day=False)
        limpio = store.get_scored_rows(30, collapse_same_day=True)

        assert len(crudo) == 4, "las duplicadas no tienen outcome: no entran a la vista"
        assert _cinco_metricas(crudo) == _cinco_metricas(limpio)

    def test_una_duplicada_sin_outcome_no_llega_a_las_metricas(self, store, zona):
        """La razón estructural: la vista se arma desde `recommendation_outcome`."""
        zona("Asia/Tokyo")
        primera, segunda = _dos_del_mismo_dia_local(datetime(2026, 8, 28, 12, 0, 0))
        _insert(store, symbol="NVDA", action="BUY", when=primera)
        _insert(store, symbol="NVDA", action="BUY", when=segunda)

        assert store.get_scored_rows(30, collapse_same_day=False) == []
        assert len(store.get_recommendations()) == 2, "el crudo conserva las dos"


# --------------------------------------------------------------------------- #
#  2. Cuando venzan sí mueve — y lo que más mueve es la curva, porque compone  #
# --------------------------------------------------------------------------- #

class TestCuandoLasDuplicadasVenzan:

    @staticmethod
    def _base_con_duplicadas(store, ahora):
        """Cuatro BUY de +10 % contra un benchmark de +1 %; dos están repetidas."""
        ids = []
        for i, sym in enumerate(("NVDA", "AMD", "INTC", "MU")):
            primera, segunda = _dos_del_mismo_dia_local(ahora - timedelta(days=40 + i))
            ids.append(_insert(store, symbol=sym, action="BUY", when=primera))
            if i < 2:
                ids.append(_insert(store, symbol=sym, action="BUY", when=segunda))
        for rid in ids:
            _score(store, rid, return_pct=10.0, benchmark_return_pct=1.0, hit=True)
        return ids

    def test_la_curva_de_equity_compone_dos_veces_el_mismo_retorno(self, store, zona):
        zona("America/Argentina/Buenos_Aires")
        ahora = datetime(2026, 10, 15, 12, 0, 0)
        self._base_con_duplicadas(store, ahora)

        crudo = equity_curve(store.get_scored_rows(30, collapse_same_day=False))
        limpio = equity_curve(store.get_scored_rows(30, collapse_same_day=True))

        assert len(crudo) == 6 and len(limpio) == 4

        # 6 posiciones contra 4: 1,1^6 vs 1,1^4 y 1,01^6 vs 1,01^4.
        assert crudo.iloc[-1]["model_equity"] == pytest.approx(1.1 ** 6, rel=1e-6)
        assert limpio.iloc[-1]["model_equity"] == pytest.approx(1.1 ** 4, rel=1e-6)

        brecha_cruda = crudo.iloc[-1]["model_equity"] - crudo.iloc[-1]["benchmark_equity"]
        brecha_limpia = limpio.iloc[-1]["model_equity"] - limpio.iloc[-1]["benchmark_equity"]

        # El sesgo es asimétrico: el modelo compone más rápido que el benchmark,
        # así que duplicar ensancha la brecha que el gráfico exhibe como mérito.
        assert brecha_cruda > brecha_limpia
        assert brecha_cruda / brecha_limpia > 1.6

    def test_la_muestra_se_infla_y_las_bandas_se_angostan(self, store, zona):
        zona("Asia/Kolkata")
        ahora = datetime(2026, 10, 15, 12, 0, 0)
        self._base_con_duplicadas(store, ahora)

        crudo = summary_stats(store.get_scored_rows(30, collapse_same_day=False))
        limpio = summary_stats(store.get_scored_rows(30, collapse_same_day=True))

        assert crudo["n"] == 6 and limpio["n"] == 4
        assert crudo["n_excess"] == 6 and limpio["n_excess"] == 4
        # La tasa de acierto no se mueve acá — todas aciertan. Lo que se mueve es
        # el `n` sobre el que se apoya, que es de lo que dependen las bandas.
        assert crudo["overall_hit_rate"] == limpio["overall_hit_rate"]

    def test_hit_rate_por_accion_y_por_fuente_cuentan_de_mas(self, store, zona):
        zona("UTC")
        ahora = datetime(2026, 10, 15, 12, 0, 0)
        self._base_con_duplicadas(store, ahora)

        crudo = store.get_scored_rows(30, collapse_same_day=False)
        limpio = store.get_scored_rows(30, collapse_same_day=True)

        assert hit_rate_by_action(crudo)["BUY"]["n"] == 6
        assert hit_rate_by_action(limpio)["BUY"]["n"] == 4
        assert hit_rate_by_source(crudo)["screener"]["n"] == 6
        assert hit_rate_by_source(limpio)["screener"]["n"] == 4

    def test_la_calibracion_por_confianza_cuenta_de_mas(self, store, zona):
        zona("America/Argentina/Buenos_Aires")
        ahora = datetime(2026, 10, 15, 12, 0, 0)
        self._base_con_duplicadas(store, ahora)

        crudo = calibration_by_confidence(store.get_scored_rows(30, collapse_same_day=False))
        limpio = calibration_by_confidence(store.get_scored_rows(30, collapse_same_day=True))

        assert crudo["MEDIUM"]["n"] == 6
        assert limpio["MEDIUM"]["n"] == 4


# --------------------------------------------------------------------------- #
#  3. La misma clave que el write-side — ejercitada, no comparada como texto   #
# --------------------------------------------------------------------------- #

class TestLaClaveDeLecturaEsLaDelWriteSide:
    """El contrato que impide que las dos reglas deriven.

    No se compara el código de una contra el de la otra: se les da a las dos los
    mismos pares de instantes y se exige que decidan lo mismo. Si alguien cambia
    el corte del día en un lado, este test lo levanta.
    """

    #: Pares (offset de la primera, offset de la segunda) en horas desde la
    #: medianoche local del día ancla. Cubren los cuatro cuadrantes: mismo día
    #: local con día UTC distinto, día local distinto con día UTC igual, mismo
    #: los dos, distinto los dos.
    PARES = [(9, 22), (9, 9), (22, 22), (9, 33), (22, 33), (1, 47)]

    @pytest.mark.parametrize("tz,_off", ZONAS)
    @pytest.mark.parametrize("h1,h2", PARES)
    def test_las_dos_reglas_deciden_lo_mismo(self, store, zona, tz, _off, h1, h2):
        zona(tz)
        import analysis.track_record as tr

        medianoche = local_day_start_utc(datetime(2026, 5, 14, 12, 0, 0))
        t1, t2 = medianoche + timedelta(hours=h1), medianoche + timedelta(hours=h2)
        assert t1 <= t2, "el write-side sólo ve filas ya escritas: t1 es la anterior"

        rid1 = _insert(store, symbol="AAPL", action="BUY", when=t1)

        # --- write-side: ¿rechazaría la segunda? ---
        original = tr.utc_now
        tr.utc_now = lambda: t2
        try:
            rechaza_el_write_side = store._exists_today("AAPL", "BUY")  # noqa: SLF001
        finally:
            tr.utc_now = original

        # --- read-side: ¿la colapsaría? ---
        rid2 = _insert(store, symbol="AAPL", action="BUY", when=t2)
        filas = [
            {"rec_id": rid1, "symbol": "AAPL", "action": "BUY", "created_at": t1},
            {"rec_id": rid2, "symbol": "AAPL", "action": "BUY", "created_at": t2},
        ]
        colapsa_el_read_side = len(collapse_same_local_day(filas)) == 1

        assert rechaza_el_write_side == colapsa_el_read_side, (
            f"{tz}: write-side {'rechaza' if rechaza_el_write_side else 'acepta'} la "
            f"segunda pero read-side {'la colapsa' if colapsa_el_read_side else 'la deja'}"
        )

    @pytest.mark.parametrize("tz,_off", ZONAS)
    def test_symbol_y_action_distintos_nunca_se_colapsan(self, store, zona, tz, _off):
        """La clave son tres campos, no la fecha sola."""
        zona(tz)
        t1, t2 = _dos_del_mismo_dia_local(datetime(2026, 5, 14, 12, 0, 0))
        filas = [
            {"rec_id": 1, "symbol": "AAPL", "action": "BUY", "created_at": t1},
            {"rec_id": 2, "symbol": "MSFT", "action": "BUY", "created_at": t2},
            {"rec_id": 3, "symbol": "AAPL", "action": "HOLD", "created_at": t2},
        ]
        assert len(collapse_same_local_day(filas)) == 3

    @pytest.mark.parametrize("tz,_off", ZONAS)
    def test_la_clave_normaliza_el_simbolo_como_lo_hace_el_write_side(self, zona, tz, _off):
        """`log_recommendation` guarda el símbolo en mayúsculas; la clave también."""
        zona(tz)
        cuando = datetime(2026, 5, 14, 15, 0, 0)
        assert (same_local_day_key("aapl", "BUY", cuando)
                == same_local_day_key("AAPL", "BUY", cuando))


# --------------------------------------------------------------------------- #
#  4. Sobrevive la primera                                                     #
# --------------------------------------------------------------------------- #

class TestSobreviveLaPrimeraDelDiaLocal:

    @pytest.mark.parametrize("tz,_off", ZONAS)
    def test_se_queda_la_primera_no_la_ultima(self, zona, tz, _off):
        zona(tz)
        t1, t2 = _dos_del_mismo_dia_local(datetime(2026, 8, 28, 12, 0, 0))
        filas = [
            {"rec_id": 302, "symbol": "XOM", "action": "HOLD", "created_at": t1},
            {"rec_id": 361, "symbol": "XOM", "action": "HOLD", "created_at": t2},
        ]
        assert [r["rec_id"] for r in collapse_same_local_day(filas)] == [302]
        # Y da igual en qué orden lleguen: la vista no promete orden.
        assert [r["rec_id"] for r in collapse_same_local_day(list(reversed(filas)))] == [302]

    @pytest.mark.parametrize("tz,_off", ZONAS)
    def test_empate_exacto_de_fecha_se_rompe_por_rec_id(self, zona, tz, _off):
        """Determinismo: dos filas con el mismo instante eligen la de id menor."""
        zona(tz)
        cuando = local_day_start_utc(datetime(2026, 8, 28, 12, 0, 0)) + timedelta(hours=14)
        filas = [
            {"rec_id": 7, "symbol": "XOM", "action": "HOLD", "created_at": cuando},
            {"rec_id": 3, "symbol": "XOM", "action": "HOLD", "created_at": cuando},
        ]
        assert [r["rec_id"] for r in collapse_same_local_day(filas)] == [3]

    def test_preserva_el_orden_de_entrada(self):
        base = local_day_start_utc(datetime(2026, 8, 28, 12, 0, 0))
        filas = [
            {"rec_id": 1, "symbol": "A", "action": "BUY", "created_at": base + timedelta(hours=9)},
            {"rec_id": 2, "symbol": "B", "action": "BUY", "created_at": base + timedelta(hours=10)},
            {"rec_id": 3, "symbol": "A", "action": "BUY", "created_at": base + timedelta(hours=22)},
        ]
        assert [r["rec_id"] for r in collapse_same_local_day(filas)] == [1, 2]

    def test_una_fila_sin_fecha_pasa_entera_en_vez_de_desaparecer(self):
        """Un dato sin fecha no pertenece a ningún día — la misma regla que
        `hours_since` en `data/clock.py`. Suprimirla sería inventar a qué día va."""
        base = local_day_start_utc(datetime(2026, 8, 28, 12, 0, 0))
        filas = [
            {"rec_id": 1, "symbol": "A", "action": "BUY", "created_at": None},
            {"rec_id": 2, "symbol": "A", "action": "BUY", "created_at": base + timedelta(hours=9)},
            {"rec_id": 3, "symbol": "A", "action": "BUY", "created_at": base + timedelta(hours=22)},
        ]
        assert [r["rec_id"] for r in collapse_same_local_day(filas)] == [1, 2]

    def test_lista_vacia(self):
        assert collapse_same_local_day([]) == []


# --------------------------------------------------------------------------- #
#  5. El default, y la puerta al crudo                                         #
# --------------------------------------------------------------------------- #

class TestElDefaultYLaPuertaAlCrudo:

    def test_el_default_esta_prendido(self, store, zona):
        """Para que los dos consumidores se corrijan sin tocarse."""
        zona("America/Argentina/Buenos_Aires")
        ahora = datetime(2026, 10, 15, 12, 0, 0)
        t1, t2 = _dos_del_mismo_dia_local(ahora - timedelta(days=40))
        for cuando in (t1, t2):
            rid = _insert(store, symbol="NVDA", action="BUY", when=cuando)
            _score(store, rid, return_pct=10.0, benchmark_return_pct=1.0, hit=True)

        assert len(store.get_scored_rows(30)) == 1
        assert store.get_scored_rows(30) == store.get_scored_rows(30, collapse_same_day=True)

    def test_el_flag_apagado_devuelve_el_crudo(self, store, zona):
        """Es la puerta que borrar las filas sacaría para siempre."""
        zona("America/Argentina/Buenos_Aires")
        ahora = datetime(2026, 10, 15, 12, 0, 0)
        t1, t2 = _dos_del_mismo_dia_local(ahora - timedelta(days=40))
        for cuando in (t1, t2):
            rid = _insert(store, symbol="NVDA", action="BUY", when=cuando)
            _score(store, rid, return_pct=10.0, benchmark_return_pct=1.0, hit=True)

        assert len(store.get_scored_rows(30, collapse_same_day=False)) == 2

    def test_es_keyword_only(self, store):
        """Posicional invitaría a confundirlo con el horizonte."""
        with pytest.raises(TypeError):
            store.get_scored_rows(30, False)

    def test_no_depende_del_flag_de_escritura(self, store, zona, monkeypatch):
        """`TRACK_RECORD.dedupe_same_day` gobierna qué se **escribe**, no qué se
        cuenta. El log ya contiene filas escritas con una regla que no rige más,
        así que la lectura tiene que colapsar igual."""
        zona("America/Argentina/Buenos_Aires")
        from config import TRACK_RECORD

        monkeypatch.setattr(TRACK_RECORD, "dedupe_same_day", False)
        ahora = datetime(2026, 10, 15, 12, 0, 0)
        t1, t2 = _dos_del_mismo_dia_local(ahora - timedelta(days=40))
        for cuando in (t1, t2):
            rid = _insert(store, symbol="NVDA", action="BUY", when=cuando)
            _score(store, rid, return_pct=10.0, benchmark_return_pct=1.0, hit=True)

        assert len(store.get_scored_rows(30)) == 1


# --------------------------------------------------------------------------- #
#  6. Barrido — el riesgo real de esta solución                                #
# --------------------------------------------------------------------------- #

#: Paquetes de producción. Los tests quedan afuera a propósito: leer el crudo es
#: exactamente lo que un test tiene que poder hacer.
PAQUETES = ("analysis", "dashboard", "data", "alerts", "portfolio", "reports", "scripts")

#: `analysis/track_record.py` es la casa de la regla: ahí el acceso crudo es la
#: implementación, no un salteo.
LA_CASA = "analysis/track_record.py"

#: Los consumidores que leen `recommendation_log` **sin** pasar por el collapse,
#: cada uno con la razón por la que está bien. Como (archivo, símbolo) para que
#: la lista no pueda crecer en silencio: cada entrada se verifica que siga
#: existiendo, y cualquier acceso nuevo que no esté acá rompe el barrido.
LECTORES_DIRECTOS_PERMITIDOS = {
    ("dashboard/pages/13_Track_Record.py", "get_recommendations"): (
        "Alimenta la métrica «Recomendaciones logueadas», que es el conteo de "
        "filas que el motor efectivamente emitió. Ese número es crudo a "
        "propósito: deduplicarlo escondería que el motor repitió. Las cinco "
        "métricas de la misma página sí pasan por get_scored_rows."
    ),
}


def _accesos_al_log(path: Path) -> set[str]:
    """Accesos ejecutables al log crudo. Vía AST, así un docstring no cuenta."""
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    encontrados: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Name) and nodo.id == "RecommendationLog":
            encontrados.add("RecommendationLog")
        elif isinstance(nodo, ast.Attribute) and nodo.attr == "get_recommendations":
            encontrados.add("get_recommendations")
        elif isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
            texto = nodo.value.lower()
            if "recommendation_log" in texto and ("select" in texto or "from" in texto):
                encontrados.add("sql_crudo")
    return encontrados


def test_ningun_consumidor_nuevo_lee_el_log_salteandose_el_collapse():
    """El riesgo real de deduplicar en lectura en vez de borrar.

    Borrar las filas haría imposible este error; no borrarlas lo deja posible, y
    esto es lo que lo compensa. Un lector directo nuevo tiene que justificarse en
    `LECTORES_DIRECTOS_PERMITIDOS` o romper el build.
    """
    infractores = []
    for paquete in PAQUETES:
        for path in sorted((ROOT / paquete).rglob("*.py")):
            rel = str(path.relative_to(ROOT))
            if rel == LA_CASA:
                continue
            for simbolo in sorted(_accesos_al_log(path)):
                if (rel, simbolo) not in LECTORES_DIRECTOS_PERMITIDOS:
                    infractores.append(f"{rel}: {simbolo}")

    assert not infractores, (
        "Lectores nuevos del log crudo, sin pasar por collapse_same_local_day:\n  "
        + "\n  ".join(infractores)
        + "\n\nSi el acceso es correcto, agregalo a LECTORES_DIRECTOS_PERMITIDOS "
          "con la razón. Si no, leelo por get_scored_rows()."
    )


def test_cada_permiso_del_barrido_sigue_existiendo():
    """Un allowlist que sobrevive al código que describía deja de proteger."""
    muertos = [
        f"{rel}: {simbolo}"
        for (rel, simbolo) in LECTORES_DIRECTOS_PERMITIDOS
        if simbolo not in _accesos_al_log(ROOT / rel)
    ]
    assert not muertos, f"Permisos que ya no describen nada real: {muertos}"


def test_los_dos_consumidores_de_las_metricas_pasan_por_get_scored_rows():
    """Confirmado el 2026-08-30: son exactamente estos dos, y no hay un tercero."""
    esperados = {"dashboard/pages/13_Track_Record.py", "dashboard/shared.py"}
    encontrados = {
        str(path.relative_to(ROOT))
        for paquete in PAQUETES
        for path in (ROOT / paquete).rglob("*.py")
        if "get_scored_rows" in path.read_text(encoding="utf-8")
        and str(path.relative_to(ROOT)) != LA_CASA
    }
    # `track_record_scorer.py` lo nombra en un docstring; el barrido de arriba usa
    # AST justamente por eso, pero acá alcanza con excluirlo por nombre.
    encontrados.discard("analysis/track_record_scorer.py")
    assert encontrados == esperados
