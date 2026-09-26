"""Oráculo de TEST-NET: la suite no sale a la red.

Antes de este guard, un test que bajaba datos del mercado corría sobre el
mercado del día —en el CI, con la caché vacía, siempre— y el tráfico que el
producto se tragaba (``_fetch_with_retry`` degrada a vacío ante cualquier
excepción) era invisible: 112 tests intentaban salir, 6 dependían de la
respuesta. Sin el guard, estos tests fallan: la llamada sale (o da un error
de conexión que no es ``NetworkBlockedInTest``) y nada la registra.

Ninguno sale a la red de verdad: el guard corta antes del socket. Cada test
consume sus propios intentos con ``drain_current`` para no disparar el fallo
por tráfico del fixture ``no_network``, que es justo lo que se está probando.
"""

from __future__ import annotations

import socket

import pytest
import requests

from tests import _network_guard as guard
from tests._network_guard import NetworkBlockedInTest

_EXTERNAL = "https://www.sec.gov/files/company_tickers.json"


def _targets() -> list:
    return [a["target"] for a in guard.drain_current()]


class TestLasTresCapasCortan:
    def test_requests(self):
        with pytest.raises(NetworkBlockedInTest):
            requests.get(_EXTERNAL, timeout=5)
        assert any("www.sec.gov" in t for t in _targets())

    def test_curl_cffi_que_usa_yfinance(self):
        curl = pytest.importorskip("curl_cffi.requests")
        with pytest.raises(NetworkBlockedInTest):
            curl.Session().get("https://query1.finance.yahoo.com/v1/test/getcrumb")
        assert any("finance.yahoo.com" in t for t in _targets())

    def test_un_socket_de_python_fuera_de_esas_dos_librerias(self):
        """httpx (los SDK de IA), ``urllib``, ``http.client``: todo pasa por aquí."""
        with pytest.raises(NetworkBlockedInTest):
            socket.create_connection(("example.com", 443), timeout=5)
        assert any("example.com" in t for t in _targets())


class TestElTraficoTragadoIgualSeVe:
    def test_un_except_del_producto_no_lo_esconde(self):
        """El caso que hace falta el registro: el producto atrapa la excepción
        y sigue con datos vacíos, así que sin registro el test quedaría verde."""
        try:
            requests.get(_EXTERNAL, timeout=5)
        except Exception:
            pass  # lo que hace _fetch_with_retry
        found = guard.drain_current()
        assert found, "el intento tragado no quedó registrado"
        assert "www.sec.gov" in guard.describe(found)

    def test_los_reintentos_se_agrupan_en_el_mensaje(self):
        for _ in range(3):
            try:
                requests.get(_EXTERNAL, timeout=5)
            except NetworkBlockedInTest:
                pass
        msg = guard.describe(guard.drain_current())
        assert "(×3)" in msg
        assert msg.count("www.sec.gov") == 1


class TestLoQueNoSeCorta:
    def test_loopback_pasa(self):
        """Un servidor local (AppTest, un hijo de test_direct_page_entry) no es red."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        try:
            client = socket.create_connection(server.getsockname(), timeout=5)
            client.close()
        finally:
            server.close()
        assert guard.drain_current() == []

    def test_allow_network_desactiva_el_corte(self, request):
        guard.begin_test(request.node.nodeid, allowed=True)
        try:
            guard._block("requests GET https://ejemplo")  # no levanta
        finally:
            guard.begin_test(request.node.nodeid)
        assert guard.drain_current() == []


def test_el_guard_esta_instalado_en_modo_estricto_por_defecto():
    """Si alguien corre la suite con RA_NETGUARD=report para medir, el guard
    bloquea pero no falla; el default tiene que ser estricto."""
    assert guard._installed
    assert guard.MODE in {"strict", "report"}
    if guard.MODE == "report":
        pytest.skip("corrida de medición (RA_NETGUARD=report)")
    assert guard.MODE == "strict"
