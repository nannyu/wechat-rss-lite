from __future__ import annotations

from dataclasses import dataclass
from itertools import cycle
from threading import Lock


@dataclass(frozen=True)
class ProxyChoice:
    url: str = ""

    @property
    def httpx_proxy(self) -> str | None:
        return self.url or None


class ProxyPool:
    def __init__(self, urls: tuple[str, ...] | list[str] = ()) -> None:
        self.urls = tuple(url for url in urls if url)
        self._cycle = cycle(self.urls) if self.urls else None
        self._lock = Lock()

    def next(self) -> ProxyChoice:
        if not self._cycle:
            return ProxyChoice()
        with self._lock:
            return ProxyChoice(next(self._cycle))

    @property
    def count(self) -> int:
        return len(self.urls)

    def status(self) -> dict[str, object]:
        return {"enabled": bool(self.urls), "size": len(self.urls)}

