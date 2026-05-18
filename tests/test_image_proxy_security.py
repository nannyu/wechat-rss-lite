from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from wechat_rss_lite.image_proxy import ImageProxy


@pytest.mark.asyncio
async def test_image_proxy_rejects_redirect_to_disallowed_host() -> None:
    proxy = ImageProxy(allowed_hosts=("mmbiz.qpic.cn",))

    async def fake_get(url: str, headers: dict) -> httpx.Response:
        if url.startswith("https://mmbiz.qpic.cn"):
            return httpx.Response(302, headers={"location": "https://evil.example/secret.jpg"})
        raise AssertionError(f"unexpected url {url}")

    mock_client = AsyncMock()
    mock_client.get = fake_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("wechat_rss_lite.image_proxy.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="not allowed"):
            await proxy.fetch("https://mmbiz.qpic.cn/a.jpg")
