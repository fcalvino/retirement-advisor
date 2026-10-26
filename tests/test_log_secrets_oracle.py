"""A failed request must not write its secret to the log (audit 2026-10-26, AUDIT-TELEGRAM-LOG).

``alerts/notifier.py`` logged ``f"Telegram alert failed: {exc}"``. The text of a ``requests``
exception carries the URL it was calling, and Telegram's API puts the bot token **in the
path**: ``https://api.telegram.org/bot<TOKEN>/sendMessage``. A connection error, a timeout
and an ``HTTPError`` all print it. The same shape sat in ``FredSource`` (``api_key=`` in the
query string) and ``FmpSource`` (``apikey=``), which log at DEBUG — and the scheduler runs
with loguru's default stderr sink, which is DEBUG and which ``launchd`` captures to a file.

Rotating a token that has already been written to a log does not help if the next network
failure writes the new one: the fix is that the log never gets it.

The fake secrets below are shaped like the real ones and are not anyone's. No network.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
import requests
from loguru import logger

import data.data_sources as ds
from alerts import notifier as notifier_mod
from config import ALERTS, MULTI_SOURCE
from data.redact import redact_secrets

TG_TOKEN = "123456789:AAFexampleTokenValue_0123456789abcdefgh"
FRED_KEY = "fredkey0123456789abcdef0123456789"
FMP_KEY = "fmpkey_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"


@pytest.fixture
def captured():
    """Every log line, at any level, as the scheduler's default sink would see it."""
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG", format="{level} {message}")
    yield lines
    logger.remove(sink)


# --------------------------------------------------------------------------- #
#  The helper                                                                  #
# --------------------------------------------------------------------------- #

class TestRedactSecrets:
    def test_a_telegram_bot_token_in_a_path(self):
        text = f"404 Client Error: Not Found for url: https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        out = redact_secrets(text)
        assert TG_TOKEN not in out and "AAFexample" not in out
        assert "api.telegram.org" in out and "sendMessage" in out      # the rest still diagnoses

    @pytest.mark.parametrize("param", ["api_key", "apikey", "key", "token", "access_token"])
    def test_a_secret_in_a_query_string(self, param):
        text = f"Max retries exceeded with url: /fred/series/observations?series_id=CPI&{param}=SECRETVALUE123&file_type=json"
        out = redact_secrets(text)
        assert "SECRETVALUE123" not in out
        assert "series_id=CPI" in out and "file_type=json" in out

    def test_a_known_secret_is_removed_wherever_it_appears(self):
        out = redact_secrets(f"boom {FMP_KEY} and again {FMP_KEY}", FMP_KEY)
        assert FMP_KEY not in out

    def test_text_without_secrets_is_untouched(self):
        text = "HTTPSConnectionPool(host='query1.finance.yahoo.com', port=443): Read timed out."
        assert redact_secrets(text) == text

    def test_it_is_idempotent(self):
        once = redact_secrets(f"https://api.telegram.org/bot{TG_TOKEN}/x?api_key=ABC")
        assert redact_secrets(once) == once

    def test_empty_or_short_known_secrets_do_not_blank_the_message(self):
        assert redact_secrets("a normal message", "", "ab") == "a normal message"


# --------------------------------------------------------------------------- #
#  The three call sites                                                        #
# --------------------------------------------------------------------------- #

class TestTelegramFailureDoesNotLogTheToken:
    def _use_token(self, monkeypatch):
        monkeypatch.setattr(notifier_mod, "ALERTS", replace(ALERTS, telegram_token=TG_TOKEN,
                                                            telegram_chat_id="42", telegram_enabled=True))

    @pytest.mark.parametrize("exc_factory", [
        lambda: requests.exceptions.ConnectionError(
            f"HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded with url: "
            f"/bot{TG_TOKEN}/sendMessage (Caused by NewConnectionError('...'))"),
        lambda: requests.exceptions.HTTPError(
            f"401 Client Error: Unauthorized for url: https://api.telegram.org/bot{TG_TOKEN}/sendMessage"),
        lambda: requests.exceptions.ConnectTimeout(
            f"HTTPSConnectionPool(host='api.telegram.org', port=443): Read timed out. (url /bot{TG_TOKEN}/sendMessage)"),
    ], ids=["connection", "http-401", "timeout"])
    def test_the_token_never_reaches_the_log(self, monkeypatch, captured, exc_factory):
        self._use_token(monkeypatch)

        def boom(*a, **k):
            raise exc_factory()

        monkeypatch.setattr(notifier_mod.requests, "post", boom)
        notifier_mod.Notifier()._send_telegram("hola")
        log = "\n".join(captured)
        assert "Telegram alert failed" in log
        assert TG_TOKEN not in log and "AAFexample" not in log


class TestDataSourcesDoNotLogTheirKeys:
    def test_fred(self, monkeypatch, captured):
        monkeypatch.setattr(MULTI_SOURCE, "fred_api_key", FRED_KEY)

        def boom(url, params=None, **k):
            raise requests.exceptions.ConnectionError(
                f"Max retries exceeded with url: /fred/series/observations?series_id=CPIAUCSL&api_key={FRED_KEY}&file_type=json")

        monkeypatch.setattr("requests.get", boom)
        assert ds.FredSource().latest_series_value("CPIAUCSL") is None
        log = "\n".join(captured)
        assert "FredSource: CPIAUCSL failed" in log
        assert FRED_KEY not in log

    def test_fmp(self, monkeypatch, captured):
        monkeypatch.setattr(MULTI_SOURCE, "fmp_api_key", FMP_KEY)

        def boom(url, params=None, **k):
            raise requests.exceptions.ConnectionError(
                f"Max retries exceeded with url: /api/v3/profile/AAPL?apikey={FMP_KEY}")

        monkeypatch.setattr("requests.get", boom)
        assert ds.FmpSource().fetch_fundamentals("AAPL") == {}
        log = "\n".join(captured)
        assert "FmpSource: AAPL failed" in log
        assert FMP_KEY not in log


class TestTheManualDiagnosticScript:
    def test_it_does_not_print_part_of_the_secret(self):
        """``token[:20]`` printed the bot id and ~10 characters of the 35-character secret to a
        terminal that gets pasted into chats."""
        from pathlib import Path

        src = Path("scripts/test_telegram.py").read_text(encoding="utf-8")
        assert "token[:" not in src
        assert "redact_secrets" in src
