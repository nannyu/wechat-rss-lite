from __future__ import annotations

from .client import WeChatArticleClient
from .models import Article, Subscription
from .rss import render_rss
from .storage import SQLiteRepository


class WeChatRssService:
    def __init__(
        self,
        *,
        repository: SQLiteRepository | None = None,
        article_client: WeChatArticleClient | None = None,
    ) -> None:
        self.repository = repository or SQLiteRepository()
        self.article_client = article_client or WeChatArticleClient()

    async def close(self) -> None:
        await self.article_client.aclose()

    async def fetch_and_store(self, url: str, *, subscription_id: str | None = None) -> Article:
        article = await self.article_client.fetch_article(url)
        self.repository.save_article(article, subscription_id=subscription_id)
        return article

    def subscribe(
        self,
        subscription_id: str,
        title: str,
        source_url: str = "",
        account_id: str = "",
    ) -> Subscription:
        subscription = Subscription(
            id=subscription_id,
            title=title,
            account_id=account_id or subscription_id,
            source_url=source_url,
        )
        self.repository.add_subscription(subscription)
        return subscription

    def render_feed(
        self,
        *,
        title: str,
        link: str,
        description: str = "",
        subscription_id: str | None = None,
        limit: int = 20,
    ) -> str:
        articles = self.repository.recent_articles(subscription_id=subscription_id, limit=limit)
        return render_rss(title=title, link=link, description=description, articles=articles)
