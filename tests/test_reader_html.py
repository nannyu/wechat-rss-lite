from __future__ import annotations

from wechat_rss_lite.api.reader import build_reader_html as _build_reader_html
from wechat_rss_lite.content_processor import reader_body_from_html


def test_reader_body_from_html_extracts_js_content() -> None:
    html = (
        '<div id="js_top_ad_area"></div>'
        '<div id="js_content"><p>正文</p><img src="/image?url=https%3A%2F%2Fmmbiz.qpic.cn%2Fa.jpg"></div>'
        '<p style="display:none">footer</p>'
    )
    body = reader_body_from_html(html)
    assert "正文" in body
    assert "/image?url=" in body
    assert "js_top_ad_area" not in body


def test_build_reader_html_includes_images() -> None:
    page = _build_reader_html(
        {
            "title": "Demo",
            "url": "https://mp.weixin.qq.com/s/demo",
            "content_html": (
                '<div id="js_content"><img src="/image?url=https%3A%2F%2Fmmbiz.qpic.cn%2Fx.jpg"></div>'
            ),
            "text": "",
        }
    )
    assert "/image?url=" in page
    assert "<img" in page


def test_build_reader_html_rebases_proxy_images() -> None:
    page = _build_reader_html(
        {
            "title": "Demo",
            "url": "https://mp.weixin.qq.com/s/demo",
            "content_html": (
                '<div id="js_content">'
                '<img src="/image?url=https%3A%2F%2Fmmbiz.qpic.cn%2Fx.jpg" '
                'data-src="/image?url=https%3A%2F%2Fmmbiz.qpic.cn%2Fx.jpg">'
                "</div>"
            ),
            "text": "",
        },
        image_proxy_base="https://example.com/_/wechat-rss-lite/image",
    )

    assert 'src="https://example.com/_/wechat-rss-lite/image?url=' in page
    assert 'data-src="https://example.com/_/wechat-rss-lite/image?url=' in page
