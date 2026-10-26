"""Take secrets out of text before it is logged.

The text of a ``requests`` exception carries the URL it was calling, and several APIs this
project talks to put the credential in it: Telegram in the **path** (``/bot<TOKEN>/sendMessage``),
FRED and FMP in the **query string** (``api_key=``, ``apikey=``). ``logger.error(f"... {exc}")``
therefore wrote the secret to the log (AUDIT-TELEGRAM-LOG). Rotating a leaked token only helps
if the next network failure does not write the new one, so the sites that log request errors
pass the message through here.

Pure: no I/O, no config import.
"""

from __future__ import annotations

import re

#: ``bot<digits>:<token>`` — what Telegram puts in the path of every Bot API call.
_TELEGRAM_BOT = re.compile(r"(bot)\d{6,}:[A-Za-z0-9_-]{20,}")
#: ``api_key=…`` and its relatives in a query string (up to the next separator).
_QUERY_SECRET = re.compile(
    r"(?i)\b(api_key|apikey|access_token|token|key)=[^&\s'\"<>)]+"
)

#: A known secret shorter than this is not replaced: blanking a 2-character string would
#: mangle the message, and a real key is never that short.
_MIN_KNOWN_SECRET_LEN = 6

REDACTED = "<redacted>"


def redact_secrets(text: str, *known_secrets: str) -> str:
    """``text`` with credentials replaced by ``<redacted>``.

    Removes, in this order: each value in ``known_secrets`` (exact match, wherever it
    appears), a Telegram ``bot<id>:<token>`` path segment, and ``key=value`` pairs for the
    usual credential parameter names. What remains still says which host and path failed.
    Idempotent.
    """
    out = str(text)
    for secret in known_secrets:
        if secret and len(secret) >= _MIN_KNOWN_SECRET_LEN:
            out = out.replace(secret, REDACTED)
    out = _TELEGRAM_BOT.sub(rf"\1{REDACTED}", out)
    out = _QUERY_SECRET.sub(rf"\1={REDACTED}", out)
    return out
