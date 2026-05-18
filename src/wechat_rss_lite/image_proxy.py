from __future__ import annotations

from urllib.parse import urlparse

import httpx


class ImageProxy:
    def __init__(self, *, allowed_hosts: tuple[str, ...], timeout: float = 15.0) -> None:
        self.allowed_hosts = allowed_hosts
        self.timeout = timeout

    async def fetch(self, url: str) -> tuple[bytes, str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only http and https image URLs are allowed")
        if self.allowed_hosts and parsed.hostname not in self.allowed_hosts:
            raise ValueError("Image host is not allowed")
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"referer": "https://mp.weixin.qq.com/"})
            response.raise_for_status()
        return response.content, response.headers.get("content-type", "application/octet-stream")

