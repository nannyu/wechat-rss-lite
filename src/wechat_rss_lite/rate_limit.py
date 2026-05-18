from __future__ import annotations

import asyncio
import time
from collections import deque


class AsyncRateLimiter:
    def __init__(self, *, per_minute: int = 6, min_interval_seconds: float = 10.0) -> None:
        self.per_minute = max(1, per_minute)
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._events: deque[float] = deque()
        self._last_request = 0.0
        self._total_requests = 0
        self._total_waits = 0
        self._total_wait_seconds = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._events and now - self._events[0] >= 60:
                self._events.popleft()
            if len(self._events) >= self.per_minute:
                wait_seconds = 60 - (now - self._events[0])
                self._record_wait(wait_seconds)
                await asyncio.sleep(wait_seconds)
                now = time.monotonic()
            gap = now - self._last_request
            if gap < self.min_interval_seconds:
                wait_seconds = self.min_interval_seconds - gap
                self._record_wait(wait_seconds)
                await asyncio.sleep(wait_seconds)
                now = time.monotonic()
            self._events.append(now)
            self._last_request = now
            self._total_requests += 1

    def configure(self, *, per_minute: int | None = None, min_interval_seconds: float | None = None) -> None:
        if per_minute is not None:
            self.per_minute = max(1, per_minute)
        if min_interval_seconds is not None:
            self.min_interval_seconds = max(0.0, min_interval_seconds)

    def stats(self) -> dict[str, float | int]:
        now = time.monotonic()
        while self._events and now - self._events[0] >= 60:
            self._events.popleft()
        return {
            "per_minute": self.per_minute,
            "min_interval_seconds": self.min_interval_seconds,
            "requests_in_current_window": len(self._events),
            "remaining_in_current_window": max(0, self.per_minute - len(self._events)),
            "total_requests": self._total_requests,
            "total_waits": self._total_waits,
            "total_wait_seconds": round(self._total_wait_seconds, 3),
        }

    def _record_wait(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._total_waits += 1
        self._total_wait_seconds += seconds
