from wechat_rss_lite.content_processor import (
    normalize_content_image_proxy_urls,
    proxy_content_images,
    proxy_image_url,
)


def test_proxy_image_url_relative_for_api_base() -> None:
    url = "https://mmbiz.qpic.cn/demo.jpg?wx_fmt=jpeg"
    assert proxy_image_url(url, "/image").startswith("/image?url=")


def test_proxy_image_url_absolute_for_rss_base() -> None:
    url = "https://mmbiz.qpic.cn/demo.jpg?wx_fmt=jpeg"
    proxied = proxy_image_url(url, "https://example.com/image")
    assert proxied.startswith("https://example.com/image?url=")


def test_normalize_content_image_proxy_urls_strips_host() -> None:
    html = (
        '<img src="http://127.0.0.1:8080/image?url=https%3A%2F%2Fmmbiz.qpic.cn%2Fa.jpg" '
        'data-src="http://localhost:8080/image?url=https%3A%2F%2Fmmbiz.qpic.cn%2Fb.jpg">'
    )
    normalized = normalize_content_image_proxy_urls(html)
    assert "127.0.0.1" not in normalized
    assert "localhost" not in normalized
    assert normalized.count("/image?url=") == 2


def test_proxy_content_images_with_relative_base() -> None:
    html = '<img src="https://mmbiz.qpic.cn/x/640?wx_fmt=png" data-src="https://mmbiz.qpic.cn/x/640?wx_fmt=png">'
    rewritten = proxy_content_images(html, "/image")
    assert rewritten.startswith('<img src="/image?url=') or 'src="/image?url=' in rewritten
