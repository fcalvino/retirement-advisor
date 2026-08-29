"""Oracle for U5-18 — un solo reloj, y un día que es el del usuario.

La fila decía «15 `utcnow` vivos entre relojes UTC-naive y local-naive» en tres
archivos. Verificado contra el código, las dos mitades están mal:

  * **son 31, en seis archivos.** `alerts/store.py` tiene 12 y ni figura en la
    fila; `analysis/macro_rag.py` tres y `dashboard/pages/8_Alertas.py` uno.
  * **no hay ningún cruce de relojes activo.** Cada módulo es internamente
    consistente: `data/cache.py` escribe y lee con `utcnow`, `screener_store.py`
    escribe y lee con `now()`, `last_refreshed_at` se sella y se mide con el
    mismo reloj local. La edad del dato —lo primero que la fila señala— está
    bien calculada. Dos relojes en un mismo SQLite son un peligro latente, no
    una resta mal hecha.

**Lo que sí está mal es el día.** `TrackRecordStore._exists_today` corta el día
a las 00:00 **UTC**, así que para un usuario en UTC−3 el «día» corre de 21:00 a
21:00 local. El dedup funciona perfecto en sus propios términos —cero duplicados
por día UTC— y deja pasar los que importan:

    medido sobre las 394 filas reales de recommendation_log
      (símbolo, acción, día UTC)   duplicados:  0
      (símbolo, acción, día LOCAL) duplicados: 80   ← el 20 % de la muestra

    AAPL BUY, día local 2026-08-23: 09:32 y 21:12
                          en UTC:   23 12:32 y 24 00:12

Y no es cosmético. CONTEXT §8 ya dice que *«149 recomendaciones del mismo día no
son 149 datos independientes — comparten el movimiento del mercado de ese día»*.
El track record es el único juez que el motor tiene sobre sí mismo, y una quinta
parte de su muestra son observaciones repetidas del mismo día.

**El arreglo no migra nada.** Guardar en UTC es correcto —es inequívoco— y todas
las filas existentes conservan su significado. Lo que se corrige es el
**límite**: «uno por día» es un concepto humano y tiene que usar el día del
humano.

Sin red, sin Streamlit.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from data.clock import local_day_start_utc, utc_now

ROOT = Path(__file__).resolve().parents[1]


#: Zonas donde se verifica la propiedad. La lista existe porque la primera
#: versión de este archivo **codificaba UTC−3, la del autor**, y pasaba en su
#: máquina y fallaba en CI, que corre en UTC. Un verde que depende de dónde se
#: corre no es evidencia — la misma razón por la que este repo prohíbe `hash()`
#: en tests. Se incluye UTC a propósito: es el caso donde el corte local y el
#: UTC coinciden y el arreglo no debe hacer nada.
ZONAS = [
    ("America/Argentina/Buenos_Aires", -3),
    ("Asia/Tokyo", +9),
    ("UTC", 0),
    ("Asia/Kolkata", +5.5),          # offset de media hora, el que rompe los atajos
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


# --------------------------------------------------------------------------- #
#  Un solo reloj, y no el deprecado                                            #
# --------------------------------------------------------------------------- #


class TestElRelojCanonico:

    def test_utc_now_coincide_con_el_reloj_utc_del_sistema(self):
        """Derivado de la definición, no del código: lo que devuelve tiene que
        ser la hora UTC, comparada contra la fuente que no está deprecada."""
        referencia = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((utc_now() - referencia).total_seconds()) < 5

    def test_utc_now_es_naive(self):
        """Naive a propósito: es lo que ya hay guardado en el SQLite, y cambiarlo
        obligaría a migrar cada fila de cada tabla para no ganar nada."""
        assert utc_now().tzinfo is None

    def test_no_emite_la_advertencia_de_deprecacion(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            utc_now()          # `datetime.utcnow()` explotaría acá


class TestNingunModuloDeProduccionUsaElRelojDeprecado:

    #: Los seis archivos que la auditoría encontró, no los tres que la fila lista.
    SOSPECHOSOS = [
        "alerts/store.py",
        "analysis/track_record.py",
        "data/cache.py",
        "analysis/macro_rag.py",
        "dashboard/pages/8_Alertas.py",
        "analysis/track_record_scorer.py",
    ]

    def test_el_barrido_no_encuentra_utcnow_en_ningun_lado(self):
        """Incluye los tests a propósito.

        Un test que llama al reloj deprecado se rompe el día que Python lo saque,
        y hasta entonces ensucia la salida: la suite emitía 167 advertencias y
        ahora emite 11, ninguna de datetime. Dejar los tests afuera del barrido
        habría sido hacer la mitad del trabajo y llamarla completa.
        """
        malos = []
        for rel in sorted(
            str(p.relative_to(ROOT))
            for p in ROOT.rglob("*.py")
            if "venv" not in str(p)
            # `data/clock.py` es el módulo que REEMPLAZA a `utcnow`, así que
            # tiene que poder nombrarlo en su documentación, y este archivo lo
            # nombra para explicar qué barre. Son las dos únicas excepciones.
            and p.name not in ("clock.py", "test_clock_oracle.py")
        ):
            for n, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\butcnow\b", line):
                    malos.append(f"{rel}:{n}: {line.strip()}")
        assert not malos, (
            "`datetime.utcnow()` está deprecado y es la mitad de los dos relojes "
            "que U5-18 unifica:\n  " + "\n  ".join(malos)
        )

    def test_el_barrido_detecta_la_forma_que_dice_detectar(self):
        """Guarda sobre la guarda: un regex que no matchea nada da un verde
        vacío, que es peor que un rojo."""
        assert re.search(r"\butcnow\b", "cached_at = Column(DateTime, default=datetime.utcnow)")
        assert re.search(r"\butcnow\b", "    now = datetime.utcnow()")
        assert not re.search(r"\butcnow\b", "now = utc_now()")


# --------------------------------------------------------------------------- #
#  El día es el del usuario                                                    #
# --------------------------------------------------------------------------- #


class TestElDiaEsElDelUsuario:

    def test_devuelve_la_medianoche_local_expresada_en_utc(self):
        """Verificado por ida y vuelta, no leyendo la implementación: convertir
        el resultado a hora local tiene que dar exactamente medianoche."""
        inicio = local_day_start_utc()
        local = inicio.replace(tzinfo=timezone.utc).astimezone()
        assert (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0)

    def test_el_inicio_del_dia_nunca_esta_en_el_futuro(self):
        assert local_day_start_utc() <= utc_now()

    def test_cae_dentro_de_las_24h_previas(self):
        assert utc_now() - local_day_start_utc() < timedelta(hours=24)

    def test_dos_instantes_del_mismo_dia_local_comparten_el_limite(self):
        """La propiedad que el dedup necesita: mismo día local ⇒ mismo corte."""
        base = utc_now()
        a = local_day_start_utc(base)
        b = local_day_start_utc(base + timedelta(seconds=1))
        assert a == b

    def test_el_caso_real_que_el_dia_utc_dejaba_pasar(self, zona):
        """El duplicado medido en la base, reproducido con la zona **fijada**.

        AAPL BUY el 2026-08-23 a las 09:32 y a las 21:12 hora de Buenos Aires.
        En UTC caen en días distintos —23 y 24— y por eso el dedup no lo atrapó.
        Con el día local tienen que caer del mismo lado del corte.
        """
        zona("America/Argentina/Buenos_Aires")
        manana_utc = datetime(2026, 8, 23, 12, 32)     # 09:32 local en UTC−3
        noche_utc = datetime(2026, 8, 24, 0, 12)       # 21:12 local del MISMO día
        assert manana_utc.date() != noche_utc.date(), "el caso ya no reproduce el defecto"
        assert local_day_start_utc(manana_utc) == local_day_start_utc(noche_utc)

    @pytest.mark.parametrize("nombre,offset", ZONAS)
    def test_la_medianoche_local_es_medianoche_en_toda_zona(self, zona, nombre, offset):
        """La propiedad, comprobada donde el offset no es cero, donde es cero, y
        donde es de media hora."""
        zona(nombre)
        inicio = local_day_start_utc(datetime(2026, 8, 23, 12, 32))
        local = inicio.replace(tzinfo=timezone.utc).astimezone()
        assert (local.hour, local.minute) == (0, 0), (
            f"{nombre}: el corte cae a las {local.hour:02d}:{local.minute:02d} local"
        )

    @pytest.mark.parametrize("nombre,offset", ZONAS)
    def test_el_corte_separa_los_dias_de_esa_zona_y_no_los_de_utc(self, zona, nombre, offset):
        """Lo que el arreglo hace, dicho como propiedad y no como caso.

        Dos instantes están del mismo lado del corte si y sólo si caen en el
        mismo día **de esa zona**. En UTC eso coincide con el día UTC, y por eso
        UTC está en la lista: es el caso donde el arreglo no cambia nada.
        """
        zona(nombre)
        base = datetime(2026, 8, 23, 12, 0)
        for horas in range(0, 48, 3):
            otro = base + timedelta(hours=horas)
            mismo_dia_local = (
                local_day_start_utc(base) == local_day_start_utc(otro)
            )
            dia_local_base = base.replace(tzinfo=timezone.utc).astimezone().date()
            dia_local_otro = otro.replace(tzinfo=timezone.utc).astimezone().date()
            assert mismo_dia_local == (dia_local_base == dia_local_otro), (
                f"{nombre}: {base} vs {otro} — el corte no coincide con el día local"
            )


# --------------------------------------------------------------------------- #
#  El dedup, de punta a punta                                                  #
# --------------------------------------------------------------------------- #


def _decision(symbol="AAPL", action="BUY"):
    return SimpleNamespace(
        symbol=symbol, action=action, confidence="HIGH", total_score=72.0,
        adjusted_score=72.0, reasons=[], risks=[], notes={}, warnings=[],
    )


class TestElDedupUsaElDiaDelUsuario:

    def test_dos_corridas_del_mismo_dia_local_dejan_una_sola_fila(self, monkeypatch, zona):
        """De punta a punta: la mañana y la noche del mismo día local, aunque el
        día UTC cambie en el medio. Con la zona fijada, no la de quien corra."""
        zona("America/Argentina/Buenos_Aires")
        import analysis.track_record as tr

        store = tr.TrackRecordStore(db_path=":memory:")
        manana = datetime(2026, 8, 23, 12, 32)         # 09:32 local
        noche = datetime(2026, 8, 24, 0, 12)           # 21:12 local, mismo día

        for instante in (manana, noche):
            monkeypatch.setattr(tr, "utc_now", lambda i=instante: i)
            store.log_recommendation(_decision(), source="test")

        filas = store.get_recommendations(limit=50)
        assert len(filas) == 1, (
            f"quedaron {len(filas)} filas para la misma recomendación en el mismo "
            f"día local — es el duplicado que infla la muestra del track record"
        )

    def test_dos_dias_locales_distintos_dejan_dos_filas(self, monkeypatch, zona):
        """Anti-cheat: el arreglo aprieta un límite, no apaga el registro."""
        zona("America/Argentina/Buenos_Aires")
        import analysis.track_record as tr

        store = tr.TrackRecordStore(db_path=":memory:")
        for instante in (
            datetime(2026, 8, 23, 12, 32),     # 09:32 local del 23
            datetime(2026, 8, 24, 12, 32),     # 09:32 local del 24
        ):
            monkeypatch.setattr(tr, "utc_now", lambda i=instante: i)
            store.log_recommendation(_decision(), source="test")

        assert len(store.get_recommendations(limit=50)) == 2

    def test_lo_que_se_guarda_sigue_siendo_utc(self, monkeypatch):
        """El arreglo no migra nada: cambia el límite, no el almacenamiento.

        Guardar en UTC es lo correcto —es inequívoco— y toda fila ya escrita
        conserva su significado.
        """
        import analysis.track_record as tr

        store = tr.TrackRecordStore(db_path=":memory:")
        instante = datetime(2026, 8, 24, 0, 12)
        monkeypatch.setattr(tr, "utc_now", lambda: instante)
        store.log_recommendation(_decision(), source="test")

        (fila,) = store.get_recommendations(limit=5)
        assert fila.created_at == instante


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
