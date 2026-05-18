from datetime import datetime, timezone
from xml.etree import ElementTree

from wechat_rss_lite.models import Article
from wechat_rss_lite.rss import render_rss


def test_render_rss_outputs_valid_xml() -> None:
    xml = render_rss(
        title="Feed",
        link="https://example.com/rss.xml",
        description="Desc",
        articles=[
            Article(
                url="https://mp.weixin.qq.com/s/a",
                title="A",
                summary="Summary",
                content_html="<p>Full content</p>",
                published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
    )

    root = ElementTree.fromstring(xml)

    assert root.tag == "rss"
    assert root.find("./channel/title").text == "Feed"
    assert root.find("./channel/item/title").text == "A"
    assert root.find("./channel/item/{http://purl.org/rss/1.0/modules/content/}encoded").text == "<p>Full content</p>"


def test_render_rss_can_proxy_content_images() -> None:
    xml = render_rss(
        title="Feed",
        link="https://example.com/rss.xml",
        description="Desc",
        image_proxy_base="https://example.com/image",
        articles=[
            Article(
                url="https://mp.weixin.qq.com/s/a",
                title="A",
                content_html='<p><img src="https://mmbiz.qpic.cn/a.jpg"></p>',
                published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
    )

    assert "https://example.com/image?url=https%3A%2F%2Fmmbiz.qpic.cn%2Fa.jpg" in xml
