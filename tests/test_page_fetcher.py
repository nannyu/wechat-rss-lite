from __future__ import annotations

import pytest

from wechat_rss_lite.page_fetcher import fetch_page
from wechat_rss_lite.proxy import ProxyPool


@pytest.mark.asyncio
async def test_fetch_page_works_without_proxy_pool_count_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_do_fetch(
        url: str,
        headers: dict,
        timeout: float,
        proxy: str | None,
        tls_verify: bool,
    ) -> str:
        return '<div id="js_content"><p>ok</p></div>'

    monkeypatch.setattr("wechat_rss_lite.page_fetcher._do_fetch", fake_do_fetch)
    html = await fetch_page("https://mp.weixin.qq.com/s/test", proxy_pool=ProxyPool())
    assert "js_content" in html
