from __future__ import annotations

from typing import Any

from .context import ApiContext
from .serializers import article_to_dict


async def refresh_article_targets(ctx: ApiContext, targets: list[dict[str, str]]) -> dict[str, Any]:
    refreshed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for target in targets:
        try:
            article = await ctx.article_client.fetch_article(target["url"])
            ctx.repo.save_article(
                article,
                subscription_id=target.get("subscription_id") or None,
                source=target.get("source") or article.source,
            )
            refreshed.append(article_to_dict(article, image_proxy_base=ctx.api_image_proxy_base))
        except Exception as exc:
            failed.append({"url": target["url"], "error": str(exc)})
    return {
        "requested": len(targets),
        "refreshed": len(refreshed),
        "failed": len(failed),
        "items": refreshed,
        "errors": failed,
    }
