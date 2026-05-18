from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from .content_processor import extract_script_vars, process_article_content
from .exceptions import ParseError
from .models import Article


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
    script_vars = extract_script_vars(raw_html)
    content = process_article_content(raw_html, url)
    title = _first(
        meta.get("og:title"),
        meta.get("twitter:title"),
        script_vars.get("msg_title"),
        _extract_title(raw_html),
    )
    if not title:
        raise ParseError("Unable to find article title")

    return Article(
        url=url,
        title=title,
        author=_first(meta.get("author"), meta.get("og:article:author"), script_vars.get("nickname")),
        account_name=_first(meta.get("og:site_name"), script_vars.get("nickname")),
        summary=_first(meta.get("description"), meta.get("og:description"), script_vars.get("msg_desc")),
        content_html=content.content_html,
        text=content.text,
        content_type=content.content_type,
        unavailable_reason=content.unavailable_reason,
        status=_status_for_content(content.content_type),
        published_at=_parse_timestamp(script_vars.get("ct")),
        images=content.images,
    )


def _extract_meta(raw_html: str) -> dict[str, str]:
    parser = _MetaExtractor()
    parser.feed(raw_html)
    return parser.meta


def _extract_title(raw_html: str) -> str:
    match = re.search(r"<title\b[^>]*>(?P<title>.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return html.unescape(_strip_tags(match.group("title"))).strip()


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


def _status_for_content(content_type: str) -> str:
    if content_type == "verification_required":
        return "verification_required"
    if content_type == "unavailable":
        return "permanent_fail"
    return "fetched"
