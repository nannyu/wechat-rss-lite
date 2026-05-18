from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

DEFAULT_WECHAT_IMAGE_HOSTS = frozenset(
    {
        "mmbiz.qpic.cn",
        "mmbiz.qlogo.cn",
        "wx.qlogo.cn",
        "res.wx.qq.com",
    }
)

_MAX_REDIRECTS = 5


class ImageProxy:
    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        timeout: float = 15.0,
        credential_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self.allowed_hosts = frozenset(host.lower() for host in (allowed_hosts or tuple(DEFAULT_WECHAT_IMAGE_HOSTS)))
        self.timeout = timeout
        self.credential_getter = credential_getter

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only http and https image URLs are allowed")
        hostname = (parsed.hostname or "").lower()
        if hostname not in self.allowed_hosts:
            raise ValueError("Image host is not allowed")

    async def fetch(self, url: str) -> tuple[bytes, str]:
        decoded = html.unescape(url)
        self._validate_url(decoded)
        headers = {
            "Referer": "https://mp.weixin.qq.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        credential = self.credential_getter() if self.credential_getter else None
        if credential is not None:
            cookie = getattr(credential, "cookie", "") or ""
            if cookie:
                headers["Cookie"] = cookie
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            current = decoded
            for _ in range(_MAX_REDIRECTS + 1):
                self._validate_url(current)
                response = await client.get(current, headers=headers)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        response.raise_for_status()
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                return response.content, response.headers.get("content-type", "application/octet-stream")
        raise ValueError("Too many image proxy redirects")
