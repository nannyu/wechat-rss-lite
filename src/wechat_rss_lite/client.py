from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

from .content_processor import detect_unavailable, detect_verification
from .exceptions import FetchError
from .models import Article
from .page_fetcher import fetch_page
from .parser import parse_article_html
from .proxy import ProxyPool
from .rate_limit import AsyncRateLimiter

DEFAULT_HEADERS = {
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

ALLOWED_ARTICLE_HOSTS = {"mp.weixin.qq.com"}
MAX_REDIRECTS = 5


class WeChatArticleClient:
    def __init__(
        self,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        proxy_pool: ProxyPool | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
        credential_getter: Callable[[], Any | None] | None = None,
        token: str = "",
        cookie: str = "",
        image_proxy_base: str = "",
        tls_verify: bool = True,
    ) -> None:
        self.retries = retries
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.timeout = timeout
        self.proxy_pool = proxy_pool or ProxyPool()
        self.rate_limiter = rate_limiter
        self.credential_getter = credential_getter
        self.token = token
        self.cookie = cookie
        self.image_proxy_base = image_proxy_base
        self.tls_verify = tls_verify
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
        )

    async def __aenter__(self) -> "WeChatArticleClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def fetch_article(self, url: str) -> Article:
        html = await self.fetch_html(url)
        return parse_article_html(html, url=url, image_proxy_base=self.image_proxy_base)

    async def fetch_html(self, url: str) -> str:
        _validate_wechat_article_url(url)
        last_error: Exception | None = None
        requested_url = self._url_with_token(url)
        extra_headers = {"Referer": "https://mp.weixin.qq.com/"}
        cookie = self._credential_value("cookie") or self.cookie
        if cookie:
            extra_headers["Cookie"] = cookie
        for attempt in range(self.retries + 1):
            try:
                if self.rate_limiter:
                    await self.rate_limiter.wait()
                html = await fetch_page(
                    requested_url,
                    extra_headers=extra_headers,
                    timeout=self.timeout,
                    proxy_pool=self.proxy_pool,
                    tls_verify=self.tls_verify,
                )
                if _has_complete_article_html(html):
                    return html
                if _is_permanent_or_actionable_response(html):
                    return html
                last_error = FetchError(_invalid_content_hint(html))
            except Exception as exc:
                last_error = exc
            if attempt < self.retries:
                await asyncio.sleep(0.5 * (attempt + 1))
        raise FetchError(f"Unable to fetch {url}") from last_error

    async def _get(self, url: str) -> httpx.Response:
        current_url = url
        response: httpx.Response | None = None
        for _redirect in range(MAX_REDIRECTS + 1):
            _validate_wechat_article_url(current_url)
            response = await self._request_once(current_url)
            if response.status_code not in {301, 302, 303, 307, 308}:
                _validate_wechat_article_url(str(response.url))
                return response
            location = response.headers.get("location")
            if not location:
                return response
            current_url = urljoin(str(response.url), location)
        raise FetchError("Too many redirects while fetching WeChat article")

    async def _request_once(self, url: str) -> httpx.Response:
        proxy = self.proxy_pool.next().httpx_proxy
        headers = self._headers_for_request()
        if not proxy or not self._owned_client:
            return await self._client.get(url, headers=headers, follow_redirects=False)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=False,
            proxy=proxy,
        ) as client:
            return await client.get(url, headers=headers)

    def _headers_for_request(self) -> dict[str, str]:
        headers = dict(self.headers)
        cookie = self._credential_value("cookie") or self.cookie
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _url_with_token(self, url: str) -> str:
        token = self._credential_value("token") or self.token
        if not token:
            return url
        parsed = urlparse(url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if any(key == "token" for key, _value in query):
            return url
        query.append(("token", token))
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _credential_value(self, name: str) -> str:
        if not self.credential_getter:
            return ""
        credential = self.credential_getter()
        if not credential:
            return ""
        if getattr(credential, "is_expired", False):
            return ""
        return str(getattr(credential, name, "") or "")


def _validate_wechat_article_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or hostname not in ALLOWED_ARTICLE_HOSTS:
        raise FetchError("Only public WeChat article URLs on mp.weixin.qq.com are allowed")


def _has_complete_article_html(raw_html: str) -> bool:
    element_markers = (
        'id="js_content"',
        "id='js_content'",
        'class="rich_media_content',
        "class='rich_media_content",
        'class="rich_media_area_primary',
        "class='rich_media_area_primary",
        'id="page-content"',
        "id='page-content'",
        'id="page_content"',
        "id='page_content'",
    )
    if any(marker in raw_html for marker in element_markers):
        return True
    if "item_show_type" in raw_html and any(
        marker in raw_html for marker in ("picture_page_info_list", "content_noencode", "common_share_audio")
    ):
        return True
    if "<mpvoice" in raw_html or "<mp-common-mpaudio" in raw_html:
        return True
    return False


def _is_permanent_or_actionable_response(raw_html: str) -> bool:
    return bool(detect_unavailable(raw_html) or detect_verification(raw_html))


def _invalid_content_hint(raw_html: str) -> str:
    lowered = raw_html.lower()
    if "验证" in raw_html or "verify" in lowered or "环境异常" in raw_html:
        return "WeChat returned a verification page"
    if "请登录" in raw_html or "login" in lowered:
        return "WeChat returned a login page"
    if "location.replace" in raw_html or "location.href" in raw_html:
        return "WeChat returned an intermediate redirect page"
    return "Fetched HTML does not contain a complete WeChat article"
