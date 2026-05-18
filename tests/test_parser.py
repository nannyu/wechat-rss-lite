from datetime import timezone

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
