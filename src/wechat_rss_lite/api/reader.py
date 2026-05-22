from __future__ import annotations

import html as html_lib
import re
from typing import Any

from ..content_processor import reader_body_from_html


def build_reader_html(article: dict[str, Any], *, image_proxy_base: str = "") -> str:
    title = html_lib.escape(article.get("title") or "未命名文章")
    meta_parts = [
        html_lib.escape(str(article.get("account_name") or article.get("author") or "")),
    ]
    published = article.get("published_at")
    if published:
        meta_parts.append(html_lib.escape(str(published)))
    source = article.get("source")
    if source:
        meta_parts.append(html_lib.escape(str(source)))
    meta = " · ".join(part for part in meta_parts if part)

    original_url = html_lib.escape(article.get("url") or "")
    original_link = (
        f'<p class="original-link"><strong>原始链接：</strong>'
        f'<a href="{original_url}" target="_blank" rel="noopener">{original_url}</a></p>'
        if original_url
        else ""
    )

    content_html = article.get("content_html") or ""
    body = reader_body_from_html(content_html) if content_html else ""
    body = rebase_reader_image_urls(body, image_proxy_base)
    if not body.strip():
        body = reader_html_from_text(article.get("text") or article.get("summary") or "")
    if not body.strip():
        body = '<p class="empty-copy">这篇文章没有保存正文内容。</p>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <base target="_blank">
  <style>
    body {{
      margin: 0;
      padding: 28px;
      color: #1E293B;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.72;
      background: #FFFFFF;
    }}
    header {{
      border-bottom: 1px solid #E2E8F0;
      margin-bottom: 24px;
      padding-bottom: 18px;
    }}
    h1 {{
      font-size: 26px;
      line-height: 1.3;
      margin: 0 0 10px;
    }}
    .meta {{
      color: #64748B;
      font-size: 13px;
    }}
    .original-link {{
      background: #F8FAFC;
      border: 1px solid #E2E8F0;
      border-radius: 8px;
      padding: 12px 14px;
      overflow-wrap: anywhere;
    }}
    .plain-text p {{
      margin: 0 0 14px;
    }}
    .plain-text h2 {{
      font-size: 20px;
      margin: 24px 0 12px;
      line-height: 1.35;
    }}
    .empty-copy {{
      color: #64748B;
    }}
    article img,
    article section img {{
      max-width: 100% !important;
      width: auto !important;
      height: auto !important;
      display: block !important;
      visibility: visible !important;
      opacity: 1 !important;
    }}
    article {{
      overflow-wrap: anywhere;
    }}
    a {{
      color: #047857;
    }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <div class="meta">{meta}</div>
  </header>
  <article>{original_link}{body}</article>
</body>
</html>"""


def reader_html_from_text(text: str) -> str:
    lines = [line.strip() for line in re.split(r"\n+", text or "") if line.strip()]
    if not lines:
        return ""
    blocks: list[str] = []
    for line in lines:
        escaped = html_lib.escape(line)
        if len(line) <= 32 and not re.search(r"[。！？!?；;]", line):
            blocks.append(f"<h2>{escaped}</h2>")
        else:
            blocks.append(f"<p>{escaped}</p>")
    return f'<div class="plain-text">{"".join(blocks)}</div>'


def rebase_reader_image_urls(body: str, image_proxy_base: str) -> str:
    base = (image_proxy_base or "").strip().rstrip("/")
    if not body or not base:
        return body

    def replace(match: re.Match[str]) -> str:
        return f'{match.group("attr")}{match.group("quote")}{base}?url='

    return re.sub(
        r'(?P<attr>\s(?:src|data-src)=)(?P<quote>["\'])/image\?url=',
        replace,
        body,
        flags=re.IGNORECASE,
    )
