from __future__ import annotations

import argparse
import asyncio
import json

from .client import WeChatArticleClient
from .rss import render_rss


def main() -> None:
    parser = argparse.ArgumentParser(prog="wechat-rss-lite")
    subcommands = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subcommands.add_parser("parse", help="Fetch and parse a public WeChat article URL")
    parse_cmd.add_argument("url")

    rss_cmd = subcommands.add_parser("rss", help="Fetch URLs and render an RSS document")
    rss_cmd.add_argument("--title", required=True)
    rss_cmd.add_argument("--link", required=True)
    rss_cmd.add_argument("--description", default="")
    rss_cmd.add_argument("urls", nargs="+")

    args = parser.parse_args()
    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    async with WeChatArticleClient() as client:
        if args.command == "parse":
            article = await client.fetch_article(args.url)
            print(
                json.dumps(
                    {
                        "url": article.url,
                        "title": article.title,
                        "author": article.author,
                        "summary": article.summary,
                        "text": article.text,
                        "images": [image.url for image in article.images],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        articles = [await client.fetch_article(url) for url in args.urls]
        print(
            render_rss(
                title=args.title,
                link=args.link,
                description=args.description,
                articles=articles,
            )
        )

