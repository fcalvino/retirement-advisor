"""Un solo reloj para todo el proyecto (U5-18).

Antes de esto había dos, y treinta y un llamadas a `datetime.utcnow()` repartidas
en seis archivos. Cada módulo era internamente consistente —`data/cache.py`
escribe y lee en UTC, `screener_store.py` escribe y lee en local— así que **no
había ninguna resta mal hecha**: la edad del dato estaba bien calculada. Dos
relojes conviviendo en un mismo SQLite son un peligro latente, no un bug activo,
y conviene decirlo así para no vender este módulo como algo que no es.

Lo que **sí** estaba mal es una cosa concreta: el límite del día.

## Guardar en UTC, cortar el día en local

Son dos decisiones distintas y las dos importan.

**Se guarda en UTC** porque es inequívoco: no tiene horario de verano, no salta
si el usuario viaja, y ordena bien. Toda fila ya escrita conserva su
significado, así que este módulo no obliga a migrar nada.

**Pero "uno por día" es un concepto humano.** `TrackRecordStore._exists_today`
cortaba a las 00:00 UTC, y para un usuario en UTC−3 eso hace que el "día" corra
de 21:00 a 21:00 local. El dedup funcionaba perfecto en sus propios términos
—cero duplicados por día UTC— y dejaba pasar los que importan. Medido sobre las
394 filas reales de `recommendation_log`:

    (símbolo, acción, día UTC)   duplicados:  0
    (símbolo, acción, día LOCAL) duplicados: 80    ← el 20 % de la muestra

    AAPL BUY, día local 2026-08-23: 09:32 y 21:12
                          en UTC:   23 12:32 y 24 00:12

Eso no es desprolijidad. CONTEXT §8 dice que *"149 recomendaciones del mismo día
no son 149 datos independientes — comparten el movimiento del mercado de ese
día"*, y el track record es el único juez que el motor tiene sobre sí mismo: una
quinta parte de su muestra eran observaciones repetidas.

## Por qué naive y no aware

Porque es lo que ya hay guardado. Pasar a `datetime` con `tzinfo` obligaría a
migrar cada fila de cada tabla —cache, track record, alertas, macro RAG— para no
ganar nada que este módulo no dé: el punto de tener un solo helper es que el
formato deja de ser una decisión que cada módulo toma por su cuenta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = ["utc_now", "local_day_start_utc", "LOCAL_DAY_NOTE"]

#: Texto para las superficies que muestran un conteo "por día", para que el
#: usuario sepa de qué día se le está hablando.
LOCAL_DAY_NOTE = "El día se cuenta según tu zona horaria, no UTC."


def utc_now() -> datetime:
    """La hora UTC, naive, sin la advertencia de deprecación.

    Reemplaza a `datetime.utcnow()`, que Python deprecó en 3.12 porque devuelve
    un naive que *parece* local y no lo es — justamente la confusión que dejó
    dos relojes en este proyecto.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_day_start_utc(now: datetime | None = None) -> datetime:
    """El instante UTC en que empezó el día **local** que contiene ``now``.

    ``now`` es un UTC naive (lo que guarda la base) y el resultado también, así
    que se puede comparar directo contra una columna sin convertir nada:

        s.query(...).filter(Log.created_at >= local_day_start_utc())

    La conversión es de ida y vuelta a propósito —UTC → local → medianoche →
    UTC— en vez de restar un offset fijo. Restar horas a mano se rompe dos veces
    al año en cualquier país con horario de verano, y se rompe en silencio.
    """
    now = utc_now() if now is None else now
    local = now.replace(tzinfo=timezone.utc).astimezone()
    medianoche_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return medianoche_local.astimezone(timezone.utc).replace(tzinfo=None)


def hours_since(stamp: datetime | None, now: datetime | None = None) -> float | None:
    """Horas transcurridas desde un UTC naive, o ``None`` si no hay marca.

    ``None`` entra y sale como ``None``: un dato sin fecha no tiene edad cero,
    no tiene edad — la misma regla que U3-1 y U5-14.
    """
    if stamp is None:
        return None
    return ((utc_now() if now is None else now) - stamp).total_seconds() / 3600.0


def within(stamp: datetime | None, window: timedelta, now: datetime | None = None) -> bool:
    """``True`` si ``stamp`` cae dentro de ``window`` hacia atrás desde ahora.

    Una marca ausente **no** está dentro de la ventana: no saber cuándo pasó algo
    no es saber que pasó recién.
    """
    if stamp is None:
        return False
    return (utc_now() if now is None else now) - stamp < window
