from __future__ import annotations

from collections.abc import Iterable
from email.utils import format_datetime
import html
import re
from urllib.parse import quote
from xml.etree.ElementTree import Element, SubElement, tostring

from .models import Article


def render_rss(
    *,
    title: str,
    link: str,
    description: str,
    articles: Iterable[Article],
    language: str = "zh-CN",
    image_proxy_base: str = "",
) -> str:
    rss = Element("rss", version="2.0", attrib={"xmlns:content": "http://purl.org/rss/1.0/modules/content/"})
    channel = SubElement(rss, "channel")
    _text(channel, "title", title)
    _text(channel, "link", link)
    _text(channel, "description", description)
    _text(channel, "language", language)

    for article in articles:
        item = SubElement(channel, "item")
        _text(item, "title", article.title)
        _text(item, "link", article.url)
        _text(item, "guid", article.url)
        _text(item, "description", article.summary or article.text[:240])
        if article.author:
            _text(item, "author", article.author)
        _text(item, "pubDate", format_datetime(article.published_or_now))
        if article.content_html:
            encoded = SubElement(item, "content:encoded")
            encoded.text = _proxy_content_images(article.content_html, image_proxy_base)

    xml = tostring(rss, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml


def _text(parent: Element, tag: str, value: str) -> None:
    child = SubElement(parent, tag)
    child.text = value


def _proxy_content_images(content_html: str, image_proxy_base: str) -> str:
    if not image_proxy_base:
        return content_html

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        source = _attr(tag, "data-original-src") or _attr(tag, "data-src") or _attr(tag, "src")
        if not source or source.startswith("data:") or "/image?url=" in source:
            return tag
        proxied = f"{image_proxy_base}?url={quote(html.unescape(source), safe='')}"
        if re.search(r"\bsrc\s*=", tag, re.IGNORECASE):
            return re.sub(r"\bsrc\s*=\s*(['\"]).*?\1", f'src="{html.escape(proxied)}"', tag, count=1)
        return tag[:-1] + f' src="{html.escape(proxied)}">'

    return re.sub(r"<img\b[^>]*>", replace, content_html, flags=re.IGNORECASE | re.DOTALL)


def _attr(tag: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*(['\"])(.*?)\1", tag, re.IGNORECASE | re.DOTALL)
    return match.group(2) if match else ""
