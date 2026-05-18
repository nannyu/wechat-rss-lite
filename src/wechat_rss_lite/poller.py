from __future__ import annotations

from datetime import datetime, timezone

from .adapters import AccountProvider, EmptyAccountProvider
from .client import WeChatArticleClient
from .models import NotificationEvent, PollResult, Subscription
from .storage import SQLiteRepository
from .webhook import WebhookNotifier


class RssPoller:
    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        account_provider: AccountProvider | None = None,
        article_client: WeChatArticleClient | None = None,
        notifier: WebhookNotifier | None = None,
    ) -> None:
        self.repository = repository
        self.account_provider = account_provider or EmptyAccountProvider()
        self.article_client = article_client or WeChatArticleClient()
        self.notifier = notifier or WebhookNotifier()

    async def poll_subscription(self, subscription: Subscription, *, limit: int = 20) -> PollResult:
        started = datetime.now(timezone.utc)
        failed = 0
        stored = 0
        summaries = await self.account_provider.list_articles(
            subscription.account_id or subscription.id,
            limit=limit,
        )
        for summary in summaries:
            try:
                article = await self.article_client.fetch_article(summary.url)
                self.repository.save_article(article, subscription_id=subscription.id)
                stored += 1
            except Exception:
                failed += 1
        result = PollResult(
            subscription_id=subscription.id,
            fetched=len(summaries),
            stored=stored,
            failed=failed,
            message="ok" if failed == 0 else f"{failed} article(s) failed",
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        )
        self.repository.record_poll_result(result)
        if failed:
            await self.notifier.send(
                NotificationEvent(
                    kind="poll.partial_failure",
                    message=result.message,
                    target=subscription.id,
                )
            )
        return result

    async def poll_all(self, *, limit_per_subscription: int = 20) -> list[PollResult]:
        results: list[PollResult] = []
        for subscription in self.repository.list_subscriptions():
            if subscription.enabled:
                results.append(
                    await self.poll_subscription(subscription, limit=limit_per_subscription)
                )
        return results

