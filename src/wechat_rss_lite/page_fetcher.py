from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .proxy import ProxyPool

BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://mp.weixin.qq.com/",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

logger = logging.getLogger(__name__)

MAX_PROXY_RETRIES = 3
_executor = ThreadPoolExecutor(max_workers=4)

try:
    from curl_cffi.requests import Session as CurlSession

    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False


async def fetch_page(
    url: str,
    *,
    extra_headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    proxy_pool: ProxyPool | None = None,
    tls_verify: bool = True,
) -> str:
    """Fetch HTML using proxy rotation and curl_cffi when available (download-api strategy)."""
    headers = {**BROWSER_HEADERS, **(extra_headers or {})}
    pool = proxy_pool or ProxyPool()
    tried: list[str] = []

    if pool.count:
        for _ in range(min(MAX_PROXY_RETRIES, pool.count)):
            choice = pool.next()
            proxy = choice.url
            if not proxy or proxy in tried:
                continue
            tried.append(proxy)
            try:
                return await _do_fetch(url, headers, timeout, proxy, tls_verify)
            except Exception as exc:
                logger.warning("fetch_page proxy=%s failed: %s", proxy, exc)

    return await _do_fetch(url, headers, timeout, None, tls_verify)


async def _do_fetch(
    url: str,
    headers: dict[str, str],
    timeout: float,
    proxy: str | None,
    tls_verify: bool,
) -> str:
    if HAS_CURL_CFFI:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor,
            _fetch_curl_cffi_sync,
            url,
            headers,
            timeout,
            proxy,
            tls_verify,
        )
    return await _fetch_httpx(url, headers, timeout, proxy, tls_verify)


def _fetch_curl_cffi_sync(
    url: str,
    headers: dict[str, str],
    timeout: float,
    proxy: str | None,
    tls_verify: bool,
) -> str:
    kwargs: dict[str, Any] = {"timeout": timeout, "allow_redirects": True, "verify": tls_verify}
    if proxy:
        kwargs["proxy"] = proxy
    with CurlSession(impersonate="chrome120") as session:
        response = session.get(url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.text


async def _fetch_httpx(
    url: str,
    headers: dict[str, str],
    timeout: float,
    proxy: str | None,
    tls_verify: bool,
) -> str:
    import httpx

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(timeout),
        "follow_redirects": True,
        "verify": tls_verify,
    }
    if proxy:
        client_kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**client_kwargs) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text
