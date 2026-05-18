from __future__ import annotations

from wechat_rss_lite.image_proxy import DEFAULT_WECHAT_IMAGE_HOSTS, ImageProxy


def test_image_proxy_allows_wechat_cdn_hosts() -> None:
    proxy = ImageProxy(allowed_hosts=tuple(DEFAULT_WECHAT_IMAGE_HOSTS))
    assert "mmbiz.qpic.cn" in proxy.allowed_hosts


def test_image_proxy_rejects_unknown_hosts() -> None:
    proxy = ImageProxy(allowed_hosts=("mmbiz.qpic.cn",))
    assert "oss.bjhiking.com" not in proxy.allowed_hosts
