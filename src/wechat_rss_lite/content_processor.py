from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

from .models import Image

_ARTICLE_MARKERS = ("js_content", "rich_media_content", "js_article", "article")
_BODY_RE = re.compile(r"<body\b[^>]*>(?P<body>.*?)</body>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"</?(?P<tag>[a-zA-Z][\w:-]*)\b[^>]*>", re.DOTALL)
_SCRIPT_VALUE_RE = re.compile(
    r"(?:var\s+|window\.)(?P<name>[a-zA-Z_][\w]*)\s*=\s*(['\"])(?P<value>.*?)\2\s*;",
    re.DOTALL,
)
_SCRIPT_NUMBER_RE = re.compile(
    r"(?:var\s+|window\.)(?P<name>[a-zA-Z_][\w]*)\s*=\s*(?P<value>\d+)\s*;",
    re.DOTALL,
)
_WECHAT_AUDIO_RE = re.compile(
    r"<(?P<tag>mpvoice|mp-common-mpaudio)\b(?P<attrs>[^>]*)>|"
    r"<div\b(?P<divattrs>[^>]*\bid=[\"']js_editor_audio[^\"']*[\"'][^>]*)>",
    re.IGNORECASE | re.DOTALL,
)
_DROP_BLOCK_RE = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ProcessedContent:
    content_html: str
    text: str
    content_type: str
    unavailable_reason: str = ""
    images: tuple[Image, ...] = field(default_factory=tuple)


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
        src = _image_source(values)
        if not src:
            return
        self.images.append(Image(url=urljoin(self.base_url, html.unescape(src)), alt=values.get("alt", "")))


def process_article_content(raw_html: str, url: str, *, image_proxy_base: str = "") -> ProcessedContent:
    script_vars = extract_script_vars(raw_html)
    verification_reason = detect_verification(raw_html)
    if verification_reason:
        return ProcessedContent(
            content_html=_placeholder("需要验证", verification_reason),
            text=verification_reason,
            content_type="verification_required",
            unavailable_reason="",
        )

    unavailable_reason = detect_unavailable(raw_html)
    if unavailable_reason:
        return ProcessedContent(
            content_html=_placeholder("内容暂不可用", unavailable_reason),
            text=unavailable_reason,
            content_type="unavailable",
            unavailable_reason=unavailable_reason,
        )

    content_type = detect_content_type(raw_html, script_vars)
    if content_type == "audio_article":
        content_html = _extract_audio_article(raw_html)
    elif content_type == "audio_share":
        content_html = _extract_audio_share(raw_html, script_vars)
    elif content_type == "image_text":
        content_html = _extract_image_text(raw_html)
    elif content_type == "short_text":
        content_html = _extract_short_text(raw_html, script_vars)
    else:
        content_html = _extract_article_body(raw_html)

    content_html = _normalize_article_html(content_html, url, image_proxy_base=image_proxy_base)
    text = html_to_text(content_html)
    images = tuple(extract_images(content_html, url))

    if images and not text:
        content_type = "image_only"
        text = f"[纯图片文章，共 {len(images)} 张图片]"
    elif content_type in {"audio_share", "audio_article"} and not text:
        text = "音频内容需要在微信中查看。"
        content_html = _placeholder("音频内容", text)

    return ProcessedContent(
        content_html=content_html,
        text=text,
        content_type=content_type,
        unavailable_reason="",
        images=images,
    )


def extract_script_vars(raw_html: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for regex in (_SCRIPT_VALUE_RE, _SCRIPT_NUMBER_RE):
        for match in regex.finditer(raw_html):
            result[match.group("name")] = html.unescape(match.group("value")).strip()
    return result


def detect_content_type(raw_html: str, script_vars: dict[str, str] | None = None) -> str:
    script_vars = script_vars or extract_script_vars(raw_html)
    item_show_type = script_vars.get("item_show_type") or _match_value(raw_html, "item_show_type")
    if _has_audio_component(raw_html):
        return "audio_article"
    if item_show_type == "7":
        return "audio_share"
    if item_show_type == "8":
        return "image_text"
    if item_show_type == "10":
        return "short_text"
    return "rich_text"


def detect_unavailable(raw_html: str) -> str:
    if detect_verification(raw_html):
        return ""
    text = _visible_text(raw_html)
    checks = (
        ("该内容已被发布者删除", "该内容已被发布者删除"),
        ("该内容已被删除", "该内容已被删除"),
        ("此内容因违规无法查看", "此内容因违规无法查看"),
        ("该内容暂时无法查看", "该内容暂时无法查看"),
        ("此帐号已被屏蔽", "此帐号已被屏蔽"),
        ("该公众号已迁移", "该公众号已迁移"),
        ("根据作者隐私设置，无法查看该内容", "根据作者隐私设置，无法查看该内容"),
        ("该内容需要权限才可查看", "该内容需要权限才可查看"),
        ("付费后可继续阅读", "该内容需要付费后查看"),
        ("开通会员后可继续阅读", "该内容需要权限才可查看"),
    )
    for marker, reason in checks:
        if marker in text:
            return reason
    if _looks_like_empty_dynamic_page(raw_html, text):
        return "动态内容为空，可能需要权限、付费或已被限制访问"
    return ""


def detect_verification(raw_html: str) -> str:
    text = _visible_text(raw_html)
    marker_groups = (
        ("环境异常", "完成验证后即可继续访问"),
        ("访问频繁", "完成验证"),
        ("当前访问存在安全风险", "验证"),
    )
    if any(all(marker in text for marker in group) for group in marker_groups):
        return "访问触发验证，稍后或人工处理后可重试。"
    if "去验证" in text and ("验证" in text or "环境" in text):
        return "访问触发验证，稍后或人工处理后可重试。"
    return ""


def extract_images(content_html: str, base_url: str) -> list[Image]:
    parser = _ImageExtractor(base_url)
    parser.feed(content_html)
    seen: set[str] = set()
    unique: list[Image] = []
    for image in parser.images:
        if image.url not in seen:
            seen.add(image.url)
            unique.append(image)
    return unique


def html_to_text(content_html: str) -> str:
    parser = _TextExtractor()
    parser.feed(content_html)
    return "\n".join(parser.parts)


def _extract_article_body(raw_html: str) -> str:
    content = _find_marked_element(raw_html)
    if content:
        return content
    body = _BODY_RE.search(raw_html)
    if body:
        return body.group("body")
    return raw_html


def _extract_image_text(raw_html: str) -> str:
    content = _extract_article_body(raw_html)
    if extract_images(content, "https://mp.weixin.qq.com/"):
        return content
    data_urls = re.findall(r"[\"'](https?://mmbiz\.qpic\.cn/[^\"']+)[\"']", raw_html)
    if data_urls:
        imgs = "".join(f'<p><img data-src="{html.escape(url)}"></p>' for url in data_urls)
        return f"<div>{imgs}</div>"
    return content


def _extract_short_text(raw_html: str, script_vars: dict[str, str]) -> str:
    content = _extract_article_body(raw_html)
    text = _visible_text(content)
    if text:
        return content
    message = script_vars.get("msg_desc") or script_vars.get("msg_title") or "短内容需要在微信中查看。"
    return f"<div><p>{html.escape(message)}</p></div>"


def _extract_audio_share(raw_html: str, script_vars: dict[str, str]) -> str:
    content = _extract_article_body(raw_html)
    text = html_to_text(content)
    if text:
        return content
    title = script_vars.get("msg_title") or "音频/视频分享"
    desc = script_vars.get("msg_desc") or "音频或视频内容由微信动态加载，需要在微信中查看。"
    return (
        "<div>"
        f"<p><strong>{html.escape(title)}</strong></p>"
        f"<p>{html.escape(desc)}</p>"
        "</div>"
    )


def _extract_audio_article(raw_html: str) -> str:
    content = _extract_article_body(raw_html)
    blocks: list[str] = []
    for match in _WECHAT_AUDIO_RE.finditer(raw_html):
        attrs = match.group("attrs") or match.group("divattrs") or ""
        name = _attr(attrs, "name") or _attr(attrs, "voice_encode_fileid") or "微信音频"
        duration = _attr(attrs, "play_length") or _attr(attrs, "duration")
        hint = f"音频：{name}"
        if duration:
            hint = f"{hint}（{duration} 秒）"
        blocks.append(f'<p data-wechat-audio="true">{html.escape(hint)}</p>')
    if blocks and "data-wechat-audio" not in content:
        return content + "".join(blocks)
    return content


def _normalize_article_html(content_html: str, base_url: str, *, image_proxy_base: str = "") -> str:
    content_html = _DROP_BLOCK_RE.sub("", content_html)
    content_html = re.sub(r"\son[a-z]+\s*=\s*(['\"]).*?\1", "", content_html, flags=re.IGNORECASE | re.DOTALL)
    content_html = _rewrite_image_tags(content_html, base_url, image_proxy_base=image_proxy_base)
    return re.sub(r">\s+<", "><", re.sub(r"\s+", " ", content_html)).strip()


def _rewrite_image_tags(content_html: str, base_url: str, *, image_proxy_base: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = _parse_attrs(tag)
        src = _image_source(attrs)
        if not src:
            return tag
        absolute = urljoin(base_url, html.unescape(src))
        rendered = f"{image_proxy_base}?url={quote(absolute, safe='')}" if image_proxy_base else absolute
        alt = attrs.get("alt", "")
        return f'<img src="{html.escape(rendered)}" data-original-src="{html.escape(absolute)}" alt="{html.escape(alt)}">'

    return re.sub(r"<img\b[^>]*>", replace, content_html, flags=re.IGNORECASE | re.DOTALL)


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


def _has_audio_component(raw_html: str) -> bool:
    return bool(_WECHAT_AUDIO_RE.search(raw_html))


def _looks_like_empty_dynamic_page(raw_html: str, text: str) -> bool:
    has_dynamic_app = bool(re.search(r'id=["\'](?:js_mp_audio|js_content|app)["\']', raw_html))
    has_article_hint = "mp.weixin.qq.com" in raw_html or "item_show_type" in raw_html
    return has_article_hint and has_dynamic_app and len(text) < 20 and not _find_marked_element(raw_html)


def _visible_text(raw_html: str) -> str:
    return html_to_text(_DROP_BLOCK_RE.sub("", raw_html))


def _image_source(attrs: dict[str, str]) -> str:
    return (
        attrs.get("data-src")
        or attrs.get("data-original")
        or attrs.get("data-backsrc")
        or attrs.get("src")
        or ""
    )


def _parse_attrs(tag: str) -> dict[str, str]:
    return {
        match.group("name").lower(): html.unescape(match.group("value") or "")
        for match in re.finditer(
            r"(?P<name>[\w:-]+)\s*=\s*(['\"])(?P<value>.*?)\2",
            tag,
            re.DOTALL,
        )
    }


def _attr(attrs: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*(['\"])(?P<value>.*?)\1", attrs, re.DOTALL)
    return html.unescape(match.group("value")).strip() if match else ""


def _match_value(raw_html: str, name: str) -> str:
    match = re.search(
        rf"{re.escape(name)}\s*=\s*['\"]?(?P<value>\d+)['\"]?",
        raw_html,
        re.IGNORECASE,
    )
    return match.group("value") if match else ""


def _placeholder(title: str, message: str) -> str:
    return f"<div><strong>{html.escape(title)}</strong><p>{html.escape(message)}</p></div>"
