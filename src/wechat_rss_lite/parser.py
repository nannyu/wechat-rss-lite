from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

from .exceptions import ParseError
from .models import Article, Image

_SCRIPT_STRING_RE = re.compile(
    r"(?:var\s+|window\.)(?P<name>msg_title|msg_desc|nickname|ct|item_show_type)\s*=\s*(['\"])(?P<value>.*?)\2\s*;",
    re.DOTALL,
)
_BODY_RE = re.compile(
    r"<body\b[^>]*>(?P<body>.*?)</body>",
    re.IGNORECASE | re.DOTALL,
)
_ARTICLE_MARKERS = ("js_content", "rich_media_content", "article")
_TAG_RE = re.compile(r"</?(?P<tag>[a-zA-Z][\w:-]*)\b[^>]*>", re.DOTALL)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)


class _ImageExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.images: list[Image] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        src = values.get("data-src") or values.get("src") or values.get("data-original")
        if not src:
            return
        self.images.append(Image(url=urljoin(self.base_url, html.unescape(src)), alt=values.get("alt", "")))


class _MetaExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        name = values.get("property") or values.get("name")
        content = values.get("content")
        if name and content:
            self.meta[name.lower()] = html.unescape(content).strip()


def parse_article_html(raw_html: str, url: str) -> Article:
    meta = _extract_meta(raw_html)
    script_vars = _extract_script_vars(raw_html)
    content_type = _detect_content_type(raw_html, script_vars)
    unavailable_reason = _detect_unavailable(raw_html)
    content_html = _extract_content(raw_html)
    title = _first(
        meta.get("og:title"),
        meta.get("twitter:title"),
        script_vars.get("msg_title"),
        _extract_title(raw_html),
    )
    if not title:
        raise ParseError("Unable to find article title")

    text = _html_to_text(content_html)
    images = tuple(_extract_images(content_html, url))
    if unavailable_reason:
        content_type = "unavailable"
        content_html = _placeholder("内容暂不可用", unavailable_reason)
        text = unavailable_reason
    elif content_type == "audio_share" and not text:
        text = "音频内容需要在微信中查看。"
        content_html = _placeholder("音频内容", text)
    elif images and not text:
        content_type = "image_only"
        text = f"[纯图片文章，共 {len(images)} 张图片]"
    return Article(
        url=url,
        title=title,
        author=_first(meta.get("author"), script_vars.get("nickname")),
        account_name=_first(meta.get("og:site_name"), script_vars.get("nickname")),
        summary=_first(meta.get("description"), meta.get("og:description"), script_vars.get("msg_desc")),
        content_html=content_html,
        text=text,
        content_type=content_type,
        unavailable_reason=unavailable_reason,
        published_at=_parse_timestamp(script_vars.get("ct")),
        images=images,
    )


def _extract_meta(raw_html: str) -> dict[str, str]:
    parser = _MetaExtractor()
    parser.feed(raw_html)
    return parser.meta


def _extract_script_vars(raw_html: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in _SCRIPT_STRING_RE.finditer(raw_html):
        result[match.group("name")] = html.unescape(match.group("value")).strip()
    return result


def _detect_content_type(raw_html: str, script_vars: dict[str, str]) -> str:
    item_show_type = script_vars.get("item_show_type") or _match_value(raw_html, "item_show_type")
    if item_show_type == "7":
        return "audio_share"
    if item_show_type == "8":
        return "image_text"
    if item_show_type == "10":
        return "short_text"
    return "rich_text"


def _detect_unavailable(raw_html: str) -> str:
    text = _html_to_text(raw_html)
    patterns = (
        "该内容已被发布者删除",
        "此内容因违规无法查看",
        "该内容已被删除",
        "该公众号已迁移",
        "此帐号已被屏蔽",
    )
    for pattern in patterns:
        if pattern in text:
            return pattern
    return ""


def _match_value(raw_html: str, name: str) -> str:
    match = re.search(
        rf"{re.escape(name)}\s*=\s*['\"](?P<value>[^'\"]+)['\"]",
        raw_html,
        re.IGNORECASE,
    )
    return match.group("value") if match else ""


def _extract_title(raw_html: str) -> str:
    match = re.search(r"<title\b[^>]*>(?P<title>.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return html.unescape(_strip_tags(match.group("title"))).strip()


def _extract_content(raw_html: str) -> str:
    content = _find_marked_element(raw_html)
    if content:
        return _normalize_html(content)
    body = _BODY_RE.search(raw_html)
    if body:
        return _normalize_html(body.group("body"))
    return _normalize_html(raw_html)


def _find_marked_element(raw_html: str) -> str:
    for start in _TAG_RE.finditer(raw_html):
        tag = start.group("tag").lower()
        if tag not in {"div", "section", "article"} or start.group(0).startswith("</"):
            continue
        if not any(marker in start.group(0) for marker in _ARTICLE_MARKERS):
            continue
        depth = 1
        for token in _TAG_RE.finditer(raw_html, start.end()):
            token_tag = token.group("tag").lower()
            if token_tag != tag:
                continue
            if token.group(0).startswith("</"):
                depth -= 1
            elif not token.group(0).rstrip().endswith("/>"):
                depth += 1
            if depth == 0:
                return raw_html[start.end() : token.start()]
    return ""


def _extract_images(content_html: str, base_url: str) -> list[Image]:
    parser = _ImageExtractor(base_url)
    parser.feed(content_html)
    seen: set[str] = set()
    unique: list[Image] = []
    for image in parser.images:
        if image.url not in seen:
            seen.add(image.url)
            unique.append(image)
    return unique


def _html_to_text(content_html: str) -> str:
    parser = _TextExtractor()
    parser.feed(content_html)
    return "\n".join(parser.parts)


def _normalize_html(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def _first(*values: str | None) -> str:
    for value in values:
        if value:
            return html.unescape(value).strip()
    return ""


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except ValueError:
        return None


def _placeholder(title: str, message: str) -> str:
    return f"<div><strong>{html.escape(title)}</strong><p>{html.escape(message)}</p></div>"
