"""La suite no sale a la red (TEST-NET).

Un test que baja datos del mercado tiene como input el mercado del día: en el CI,
que arranca con la caché vacía, siempre. Así ``test_longevity_horizon_oracle.py``
—que se declaraba «sin red»— corría Monte Carlo sobre la historia real de
SPY/BND/KO/JNJ/PG, y su verde dependía del día.

Tres capas, porque ninguna ve todo:

* ``curl_cffi.requests.Session.request`` — yfinance. ``curl_cffi`` abre sus
  sockets en C, así que la sonda de sockets de Python no lo ve (por eso
  ``pytest-socket`` no alcanzaba: vio 2 tests donde la de HTTP vio 8).
* ``requests.Session.request`` — SEC, FRED, FMP, Telegram. ``requests.get``
  crea un ``Session`` por llamada, así que parchear la clase lo cubre.
* Un audit hook sobre ``socket.connect`` / ``socket.getaddrinfo`` — todo lo
  demás que use sockets de Python (httpx de los SDK de IA, ``urllib``,
  ``http.client``, una librería futura). Loopback y ``AF_UNIX`` pasan.

Se instala **una vez, al importar** ``conftest.py`` y no como fixture: una
fixture no cubre la colección, los fixtures de sesión ni los hilos que siguen
vivos después del teardown. Un audit hook, además, no se puede desinstalar.

**Qué pasa con un intento.** Se registra (URL + pila) y se levanta
``NetworkBlockedInTest``, que hereda de ``Exception`` a propósito: el producto
degrada igual que sin red, en vez de que un ``BaseException`` atraviese el pool
de hilos del Screener o de AppTest y rompa por el lado equivocado. Pero como el
producto **se traga** esas excepciones (``_fetch_with_retry``, los ``except``
de los fetchers), el registro es lo que hace fallar al test al final — si no,
el tráfico silencioso seguiría invisible.

Modos, por ``RA_NETGUARD``:

* ``strict`` (default) — bloquea, y el test que lo intentó falla.
* ``report`` — bloquea igual (así ninguna caché se llena y esconde a los tests
  siguientes) pero no falla; con ``RA_NETGUARD_OUT=<archivo>`` vuelca el
  registro en JSON. Es la herramienta para medir la lista real.

Un test que necesite red de verdad se marca ``@pytest.mark.allow_network``.
Hoy ninguno lo hace.

Los hijos que la suite lanza con ``subprocess`` no heredan nada de esto.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import traceback
from typing import Dict, List, Optional

MODE = os.environ.get("RA_NETGUARD", "strict").strip().lower()
OUTSIDE_A_TEST = "<fuera de un test>"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}


class NetworkBlockedInTest(RuntimeError):
    """Un test intentó salir a la red."""


_lock = threading.Lock()
_current: Optional[str] = None
_allowed = False
_attempts: Dict[str, List[dict]] = {}
_installed = False


# --------------------------------------------------------------------------- #
#  Registro                                                                    #
# --------------------------------------------------------------------------- #

def begin_test(nodeid: str, *, allowed: bool = False) -> None:
    global _current, _allowed
    with _lock:
        _current = nodeid
        _allowed = allowed


def end_test() -> List[dict]:
    """Cierra el test en curso y devuelve sus intentos (vacío si no hubo)."""
    global _current, _allowed
    with _lock:
        nodeid, _current, _allowed = _current, None, False
        return list(_attempts.get(nodeid, [])) if nodeid else []


def drain_current() -> List[dict]:
    """Saca y devuelve los intentos del test en curso. Solo para el oráculo del
    guard, que provoca intentos a propósito y no debe fallar por ellos."""
    with _lock:
        return _attempts.pop(_current or OUTSIDE_A_TEST, [])


def attempts() -> Dict[str, List[dict]]:
    with _lock:
        return {k: list(v) for k, v in _attempts.items()}


def describe(found: List[dict]) -> str:
    """Una línea por destino distinto: los reintentos repiten la misma URL."""
    seen: Dict[str, int] = {}
    for a in found:
        seen[a["target"]] = seen.get(a["target"], 0) + 1
    lines = [f"  {t}" + (f"  (×{n})" if n > 1 else "") for t, n in seen.items()]
    first = found[0]["stack"] if found else ""
    return (
        "El test intentó salir a la red (TEST-NET). Stubeá la función del "
        "proyecto que hace el fetch, o marcá el test con "
        "@pytest.mark.allow_network si de verdad la necesita.\n"
        + "\n".join(lines)
        + ("\nPrimer intento desde:\n" + first if first else "")
    )


def _block(target: str) -> None:
    """Registra el intento y lo corta, salvo en un test con ``allow_network``."""
    with _lock:
        if _allowed:
            return
        key = _current or OUTSIDE_A_TEST
        _attempts.setdefault(key, []).append({
            "target": target,
            "stack": "".join(traceback.format_stack(limit=25)[:-2]),
        })
    raise NetworkBlockedInTest(f"red bloqueada en tests: {target}")


def dump(path: str) -> None:
    data = {k: sorted({a["target"] for a in v}) for k, v in attempts().items()}
    with open(path, "w") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)


# --------------------------------------------------------------------------- #
#  Las tres capas                                                              #
# --------------------------------------------------------------------------- #

def _wrap_session_class(cls, label: str) -> None:
    original = cls.request

    def request(self, method, url, *args, **kwargs):
        _block(f"{label} {method} {str(url).split('?')[0]}")
        return original(self, method, url, *args, **kwargs)

    request.__wrapped__ = original  # type: ignore[attr-defined]
    cls.request = request


def _is_local(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode(errors="ignore")
    host = str(host)
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def _audit(event: str, args) -> None:
    if event == "socket.getaddrinfo":
        host, port = args[0], args[1]
        if not _is_local(host):
            _block(f"socket getaddrinfo {host}:{port}")
    elif event == "socket.connect":
        sock, address = args[0], args[1]
        if getattr(sock, "family", None) == getattr(socket, "AF_UNIX", object()):
            return
        if isinstance(address, tuple) and address and not _is_local(address[0]):
            _block(f"socket connect {address[0]}:{address[1]}")


def install() -> None:
    """Idempotente. Lo llama ``conftest.py`` al importarse."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        from curl_cffi.requests import Session as CurlSession
    except ImportError:  # dependencia transitiva de yfinance, no propia
        CurlSession = None
    if CurlSession is not None:
        _wrap_session_class(CurlSession, "curl")
    import requests

    _wrap_session_class(requests.Session, "requests")
    sys.addaudithook(_audit)
