from datetime import timezone

from wechat_rss_lite.content_processor import proxy_content_images
from wechat_rss_lite.parser import parse_article_html


def test_parse_article_html_extracts_core_fields() -> None:
    raw = """
    <html>
      <head>
        <meta property="og:title" content="Example Title">
        <meta name="description" content="Short summary">
        <script>
          var nickname = "Example Account";
          var ct = "1700000000";
        </script>
      </head>
      <body>
        <div id="js_content">
          <p>Hello <strong>world</strong></p>
          <img data-src="/image.jpg" alt="cover">
        </div>
      </body>
    </html>
    """

    article = parse_article_html(raw, "https://mp.weixin.qq.com/s/example")

    assert article.title == "Example Title"
    assert article.account_name == "Example Account"
    assert article.summary == "Short summary"
    assert article.text == "Hello\nworld"
    assert article.images[0].url == "https://mp.weixin.qq.com/image.jpg"
    assert article.published_at is not None
    assert article.published_at.tzinfo == timezone.utc


def test_parse_article_html_handles_meta_attribute_order_and_nested_content() -> None:
    raw = """
    <html>
      <head><meta content="Ordered Title" property="og:title"></head>
      <body>
        <div id="js_content">
          <div><p>Nested text</p></div>
          <p>Tail text</p>
        </div>
      </body>
    </html>
    """

    article = parse_article_html(raw, "https://mp.weixin.qq.com/s/example")

    assert article.title == "Ordered Title"
    assert article.text == "Nested text\nTail text"


def test_parse_article_html_preserves_wechat_layout_attributes() -> None:
    raw = """
    <html>
      <head><meta property="og:title" content="Styled"></head>
      <body>
        <div id="js_content">
          <section class="layout" style="margin: 0px; padding: 12px;">
            <p style="text-align:center; line-height: 1.8;">
              <img class="rich_pages wxw-img"
                   data-src="https://mmbiz.qpic.cn/a.jpg"
                   data-ratio="0.5"
                   style="width: 100%; height: auto;"
                   alt="cover">
            </p>
          </section>
        </div>
      </body>
    </html>
    """

    article = parse_article_html(raw, "https://mp.weixin.qq.com/s/styled")

    assert 'class="layout"' in article.content_html
    assert 'style="margin: 0px; padding: 12px;"' in article.content_html
    assert 'class="rich_pages wxw-img"' in article.content_html
    assert 'data-ratio="0.5"' in article.content_html
    assert 'style="width: 100%; height: auto;"' in article.content_html
    assert 'src="https://mmbiz.qpic.cn/a.jpg"' in article.content_html
    assert 'data-original-src="https://mmbiz.qpic.cn/a.jpg"' in article.content_html


def test_parse_image_text_article_from_picture_page_info_list() -> None:
    raw = r"""
    <html>
      <head><meta property="og:title" content="Gallery"></head>
      <body>
        <script>
          window.item_show_type = '8';
          var picture_page_info_list = [
            {
              cdn_url: 'https://mmbiz.qpic.cn/one.jpg?wx_fmt=jpeg',
              watermark_info: { cdn_url: 'https://mmbiz.qpic.cn/watermark.jpg' }
            },
            {
              cdn_url: JsDecode('https://mmbiz.qpic.cn/two.jpg?x=1\x26amp;y=2')
            }
          ];
        </script>
      </body>
    </html>
    """

    article = parse_article_html(raw, "https://mp.weixin.qq.com/s/gallery")

    assert article.content_type == "image_text"
    assert [image.url for image in article.images] == [
        "https://mmbiz.qpic.cn/one.jpg?wx_fmt=jpeg",
        "https://mmbiz.qpic.cn/two.jpg?x=1&y=2",
    ]
    assert "https://mmbiz.qpic.cn/one.jpg?wx_fmt=jpeg" in article.content_html


def test_proxy_content_images_rewrites_wechat_and_third_party_hosts() -> None:
    html = (
        '<img src="https://oss.bjhiking.com/a.png-thumbnail" '
        'data-src="https://oss.bjhiking.com/a.png-thumbnail">'
        '<img src="https://mmbiz.qpic.cn/x/640?wx_fmt=png&amp;from=appmsg" '
        'data-original-src="https://mmbiz.qpic.cn/x/640?wx_fmt=png&amp;from=appmsg">'
    )
    rewritten = proxy_content_images(html, "http://127.0.0.1:8080/image")
    assert rewritten.count("/image?url=") >= 1
    assert "oss.bjhiking.com/a.png-thumbnail" in rewritten
    assert "from=appmsg" in rewritten or "from%3Dappmsg" in rewritten


def test_parse_article_html_can_rewrite_images_through_proxy() -> None:
    raw = """
    <html>
      <head><meta property="og:title" content="Demo"></head>
      <body><div id="js_content">
        <img data-src="https://mmbiz.qpic.cn/demo.jpg?wx_fmt=jpeg" src="https://mmbiz.qpic.cn/demo.jpg?wx_fmt=jpeg">
      </div></body></html>
    """
    article = parse_article_html(
        raw,
        "https://mp.weixin.qq.com/s/demo",
        image_proxy_base="http://127.0.0.1:8080/image",
    )
    assert article.images[0].url == "https://mmbiz.qpic.cn/demo.jpg?wx_fmt=jpeg"
    assert "http://127.0.0.1:8080/image?url=" in article.content_html
    assert 'data-original-src="https://mmbiz.qpic.cn/demo.jpg?wx_fmt=jpeg"' in article.content_html
