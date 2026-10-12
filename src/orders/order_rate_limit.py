"""Per-client order rate limit: at most `count` orders per `window_s` seconds per client.

In memory, per process: one platform-api worker is the whole deployment today. A refused
client gets the seconds until its oldest counted order leaves the window.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RateCheck:
    """Whether this order may proceed, and if not, the seconds to wait."""

    allowed: bool
    retry_after_s: int


class OrderRateLimiter:
    """Sliding-window counter keyed by client address."""

    def __init__(
        self,
        *,
        count: int,
        window_s: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._count = count
        self._window_s = window_s
        self._clock = clock
        self._orders: dict[str, deque[float]] = {}

    def check(self, client: str) -> RateCheck:
        """Record the order if the client is under the limit; otherwise refuse it."""
        now = self._clock()
        times = self._orders.setdefault(client, deque())
        while times and now - times[0] >= self._window_s:
            times.popleft()
        if len(times) < self._count:
            times.append(now)
            return RateCheck(allowed=True, retry_after_s=0)
        return RateCheck(
            allowed=False,
            retry_after_s=max(1, round(self._window_s - (now - times[0]))),
        )
