from __future__ import annotations

import asyncio
import time
from collections import deque


class AsyncRateLimiter:
    def __init__(self, *, per_minute: int = 30, min_interval_seconds: float = 0.0) -> None:
        self.per_minute = max(1, per_minute)
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._events: deque[float] = deque()
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._events and now - self._events[0] >= 60:
                self._events.popleft()
            if len(self._events) >= self.per_minute:
                await asyncio.sleep(60 - (now - self._events[0]))
                now = time.monotonic()
            gap = now - self._last_request
            if gap < self.min_interval_seconds:
                await asyncio.sleep(self.min_interval_seconds - gap)
                now = time.monotonic()
            self._events.append(now)
            self._last_request = now

