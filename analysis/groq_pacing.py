"""Pace Groq calls against a tokens-per-minute budget.

Free / on_demand gpt-oss-120b is 8K TPM. Serialising workers is not enough:
ten tickers in 20s still blow the minute window. This pacer sleeps until the
rolling 60s total plus the next reservation fits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class GroqTpmPacer:
    budget: int
    _events: list[tuple[float, int]] = field(default_factory=list)

    def wait_for(self, tokens: int) -> None:
        need = max(0, int(tokens))
        if self.budget <= 0 or need <= 0:
            return
        while True:
            now = time.monotonic()
            window = now - 60.0
            self._events = [(t, n) for t, n in self._events if t > window]
            used = sum(n for _, n in self._events)
            if used + need <= self.budget:
                self._events.append((now, need))
                return
            oldest = min(t for t, _ in self._events)
            time.sleep(max(0.05, oldest + 60.0 - now))
