from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse

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
        src = values.get("data-original-src") or _image_source(values)
        if not src:
            return
        decoded = html.unescape(src)
        if decoded.startswith("/image?url="):
            return
        self.images.append(Image(url=urljoin(self.base_url, decoded), alt=values.get("alt", "")))


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

    if images and not text and content_type == "rich_text":
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


def _extract_div_inner(html: str, open_tag_pattern: str) -> str:
    match = re.search(open_tag_pattern, html, re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    start = match.end()
    depth = 1
    open_re = re.compile(r"<div[\s>/]", re.IGNORECASE)
    close_re = re.compile(r"</div\s*>", re.IGNORECASE)
    pos = start
    while depth > 0 and pos < len(html):
        next_open = open_re.search(html, pos)
        next_close = close_re.search(html, pos)
        if next_close is None:
            break
        if next_open and next_open.start() < next_close.start():
            depth += 1
            pos = next_open.end()
        else:
            depth -= 1
            if depth == 0:
                return html[start : next_close.start()].strip()
            pos = next_close.end()
    return html[start:].strip()


def reader_body_from_html(content_html: str) -> str:
    """Return the main article body for the reader UI (without WeChat chrome)."""
    raw = (content_html or "").strip()
    if not raw:
        return ""
    return _extract_article_body(raw)


def _extract_article_body(raw_html: str) -> str:
    patterns = (
        r'<div[^>]*\bid=["\']js_content["\'][^>]*>',
        r'<div[^>]*\bclass=["\'][^"\']*rich_media_content[^"\']*["\'][^>]*>',
        r'<div[^>]*\bid=["\']page-content["\'][^>]*>',
        r'<div[^>]*\bclass=["\'][^"\']*rich_media_area_primary_inner[^"\']*["\'][^>]*>',
        r'<div[^>]*\bid=["\']js_article["\'][^>]*>',
    )
    for pattern in patterns:
        content = _extract_div_inner(raw_html, pattern)
        if content:
            return content
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
    data_urls = _extract_script_image_urls(raw_html)
    if data_urls:
        imgs = "".join(
            '<p style="text-align:center;margin:0 0 6px">'
            f'<img src="{html.escape(url)}" data-src="{html.escape(url)}" '
            'style="max-width:100%;height:auto">'
            "</p>"
            for url in data_urls
        )
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
    content_html = re.sub(
        r"<(script|noscript)\b[^>]*>.*?</\1>",
        "",
        content_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    content_html = re.sub(r"\son[a-z]+\s*=\s*(['\"]).*?\1", "", content_html, flags=re.IGNORECASE | re.DOTALL)
    content_html = _rewrite_image_tags(content_html, base_url, image_proxy_base=image_proxy_base)
    content_html = re.sub(r"\n\s*\n\s*\n+", "\n\n", content_html)
    return content_html.strip()


_WECHAT_IMAGE_HOST_MARKERS = ("mmbiz.qpic.cn", "mmbiz.qlogo.cn", "wx.qlogo.cn")


def is_wechat_image_url(url: str) -> bool:
    if not url or url.startswith("data:"):
        return False
    return any(marker in url for marker in _WECHAT_IMAGE_HOST_MARKERS)


def image_proxy_endpoint(image_proxy_base: str) -> str:
    base = (image_proxy_base or "").strip().rstrip("/")
    if not base:
        return "/image"
    if base.startswith(("http://", "https://")):
        parsed = urlparse(base)
        return parsed.path or "/image"
    if not base.startswith("/"):
        return f"/{base}"
    return base


def proxy_image_url(url: str, image_proxy_base: str) -> str:
    if not url:
        return ""
    decoded = html.unescape(url)
    if not decoded or decoded.startswith("data:"):
        return decoded
    if "/image?url=" in decoded:
        if decoded.startswith("/image?url="):
            return decoded
        if decoded.startswith(("http://", "https://")):
            marker = "/image?url="
            idx = decoded.find(marker)
            if idx >= 0:
                return decoded[idx:]
        return decoded
    if is_wechat_image_url(decoded):
        endpoint = image_proxy_endpoint(image_proxy_base)
        relative = f"{endpoint}?url={quote(decoded, safe='')}"
        if image_proxy_base.startswith(("http://", "https://")):
            parsed = urlparse(image_proxy_base)
            return f"{parsed.scheme}://{parsed.netloc}{relative}"
        return relative
    return decoded


def normalize_content_image_proxy_urls(content_html: str) -> str:
    if not content_html.strip():
        return content_html
    return re.sub(
        r"https?://[^/\"'\s]+(/image\?url=[^\"'\s>]+)",
        r"\1",
        content_html,
        flags=re.IGNORECASE,
    )


def proxy_content_images(content_html: str, image_proxy_base: str) -> str:
    if not image_proxy_base or not content_html.strip():
        return content_html

    def replace_img_tag(match: re.Match[str]) -> str:
        img_html = match.group(0)
        data_src_match = re.search(r'data-src=(["\'])(.*?)\1', img_html, re.IGNORECASE | re.DOTALL)
        src_match = re.search(r'\ssrc=(["\'])(.*?)\1', img_html, re.IGNORECASE | re.DOTALL)
        original_url = None
        if data_src_match:
            original_url = data_src_match.group(2)
        elif src_match:
            original_url = src_match.group(2)
        if not original_url or not is_wechat_image_url(original_url):
            return img_html
        proxy_url = proxy_image_url(original_url, image_proxy_base)
        absolute = html.unescape(original_url)
        if not absolute.startswith(("http://", "https://")):
            absolute = urljoin("https://mp.weixin.qq.com/", absolute)
        new_html = img_html
        if data_src_match:
            new_html = re.sub(
                r'data-src=(["\']).*?\1',
                f'data-src="{proxy_url}"',
                new_html,
                count=1,
                flags=re.IGNORECASE | re.DOTALL,
            )
        if src_match:
            new_html = re.sub(
                r'\ssrc=(["\']).*?\1',
                f' src="{proxy_url}"',
                new_html,
                count=1,
                flags=re.IGNORECASE | re.DOTALL,
            )
        else:
            new_html = new_html.replace("<img", f'<img src="{proxy_url}"', 1)
            if "src=" not in new_html:
                new_html = new_html.replace("<IMG", f'<IMG src="{proxy_url}"', 1)
        if "data-original-src" not in new_html.lower():
            new_html = _set_attr(new_html, "data-original-src", absolute)
        return new_html

    return re.sub(r"<img\b[^>]*>", replace_img_tag, content_html, flags=re.IGNORECASE | re.DOTALL)


def _rewrite_image_tags(content_html: str, base_url: str, *, image_proxy_base: str) -> str:
    if image_proxy_base:
        return proxy_content_images(content_html, image_proxy_base)
    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = _parse_attrs(tag)
        src = _image_source(attrs)
        if not src:
            return tag
        decoded = html.unescape(src)
        if decoded.startswith("data:") or "/image?url=" in decoded:
            return tag
        absolute = urljoin(base_url, decoded)
        rewritten = _set_attr(tag, "src", absolute)
        if "data-src" in attrs:
            rewritten = _set_attr(rewritten, "data-src", absolute)
        else:
            rewritten = _set_attr(rewritten, "data-src", absolute)
        rewritten = _set_attr(rewritten, "data-original-src", absolute)
        return rewritten

    return re.sub(r"<img\b[^>]*>", replace, content_html, flags=re.IGNORECASE | re.DOTALL)


def _extract_script_image_urls(raw_html: str) -> list[str]:
    images: list[str] = []
    simple_list_pos = raw_html.find("picture_page_info_list")
    if simple_list_pos >= 0:
        bracket_start = raw_html.find("[", simple_list_pos)
        if bracket_start >= 0:
            depth = 0
            bracket_end = bracket_start
            for bracket_end in range(bracket_start, min(bracket_start + 40000, len(raw_html))):
                char = raw_html[bracket_end]
                if char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                    if depth == 0:
                        break
            block = raw_html[bracket_start : bracket_end + 1]
            for item in _top_level_objects(block):
                match = re.search(
                    r"cdn_url\s*:\s*(?:JsDecode\()?['\"](?P<url>https?://[^'\"]+)['\"]\)?",
                    item,
                )
                if match:
                    _append_image_url(images, _decode_wechat_js(match.group("url")))
    if not images:
        for match in re.finditer(r"[\"'](?P<url>https?://(?:mmbiz\.qpic\.cn|mmbiz\.qlogo\.cn|wx\.qlogo\.cn)/[^\"']+)[\"']", raw_html):
            _append_image_url(images, _decode_wechat_js(match.group("url")))
    return images


def _top_level_objects(array_source: str) -> list[str]:
    objects: list[str] = []
    depth = 0
    start = -1
    quote: str | None = None
    escape = False
    for index, char in enumerate(array_source):
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                objects.append(array_source[start : index + 1])
                start = -1
    return objects


def _append_image_url(images: list[str], url: str) -> None:
    if url.startswith("data:"):
        return
    if not any(host in url for host in ("mmbiz.qpic.cn", "mmbiz.qlogo.cn", "wx.qlogo.cn")):
        return
    if url not in images:
        images.append(url)


def _decode_wechat_js(value: str) -> str:
    value = re.sub(r"\\x([0-9a-fA-F]{2})", lambda match: chr(int(match.group(1), 16)), value)
    return html.unescape(html.unescape(value))


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


def _set_attr(tag: str, name: str, value: str) -> str:
    escaped = html.escape(value, quote=True)
    pattern = rf"(?P<prefix>\s{re.escape(name)}\s*=\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)"
    if re.search(pattern, tag, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(pattern, rf'\g<prefix>"{escaped}"', tag, count=1, flags=re.IGNORECASE | re.DOTALL)
    insert_at = tag.rfind("/>") if tag.rstrip().endswith("/>") else tag.rfind(">")
    if insert_at < 0:
        return tag
    return f'{tag[:insert_at]} {name}="{escaped}"{tag[insert_at:]}'


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
