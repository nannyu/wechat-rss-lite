from __future__ import annotations

from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=1)
def load_admin_html() -> str:
    css = resources.files(__package__).joinpath("assets/admin.css").read_text(encoding="utf-8")
    body = resources.files(__package__).joinpath("assets/admin.body.html").read_text(encoding="utf-8")
    js = resources.files(__package__).joinpath("assets/admin.js").read_text(encoding="utf-8")
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>WeChat RSS Lite</title>\n"
        "  <style>\n"
        f"{css}\n"
        "  </style>\n"
        "</head>\n"
        f"{body}\n"
        "  <script>\n"
        f"{js}\n"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
    )
