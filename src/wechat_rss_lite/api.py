from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
import asyncio
import csv
import io
import xml.etree.ElementTree as ET
from urllib.parse import quote

from .adapters import AccountProvider, LoginProvider, ManualLoginProvider
from .admin import ADMIN_HTML
from .auth import AuthManager
from .client import WeChatArticleClient
from .config import Settings
from .image_proxy import ImageProxy
from .local_login import LocalQrLoginProvider
from .models import Article, BlacklistEntry, Category, Credential, NotificationEvent, Subscription, VerificationChallenge
from .poller import RssPoller
from .proxy import ProxyPool
from .rate_limit import AsyncRateLimiter
from .rss import render_rss
from .storage import SQLiteRepository
from .webhook import WebhookNotifier
from .wechat_account import WeChatMpAccountProvider
from .wechat_login import WeChatMpLoginProvider, validate_wechat_credential


def create_app(
    *,
    settings: Settings | None = None,
    repository: SQLiteRepository | None = None,
    account_provider: AccountProvider | None = None,
    login_provider: LoginProvider | None = None,
    article_client: WeChatArticleClient | None = None,
) -> Any:
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
        from fastapi import File, Form, UploadFile
        from fastapi.responses import HTMLResponse
        from pydantic import BaseModel, HttpUrl
    except ImportError as exc:
        raise RuntimeError("Install with wechat-rss-lite[api] to use the FastAPI app") from exc

    settings = settings or Settings.from_env()
    repo = repository or SQLiteRepository(settings.db_path)
    proxies = ProxyPool(settings.proxy_urls)
    limiter = AsyncRateLimiter(
        per_minute=settings.rate_limit_per_minute,
        min_interval_seconds=settings.article_interval_seconds,
    )
    notifier = WebhookNotifier(settings.webhook_url)
    article_client = article_client or WeChatArticleClient(
        timeout=settings.request_timeout_seconds,
        retries=settings.request_retries,
        proxy_pool=proxies,
        rate_limiter=limiter,
    )
    accounts = account_provider or WeChatMpAccountProvider(
        repository=repo,
        timeout=settings.request_timeout_seconds,
    )
    login_provider = login_provider or _build_login_provider(settings)
    auth = AuthManager(
        repository=repo,
        login_provider=login_provider,
        notifier=notifier,
    )
    poller = RssPoller(
        repository=repo,
        account_provider=accounts,
        article_client=article_client,
        notifier=notifier,
        verification_blacklist_threshold=settings.verification_blacklist_threshold,
    )
    images = ImageProxy(
        allowed_hosts=settings.allowed_image_hosts,
        timeout=settings.request_timeout_seconds,
    )

    class ParseRequest(BaseModel):
        url: HttpUrl

    class RssRequest(BaseModel):
        title: str
        link: HttpUrl
        description: str = ""
        articles: list[dict[str, Any]]

    class SubscriptionRequest(BaseModel):
        id: str
        title: str
        account_id: str = ""
        source_url: str = ""
        avatar_url: str = ""
        description: str = ""
        category_id: int | None = None
        enabled: bool = True

    class SubscriptionUpdateRequest(BaseModel):
        enabled: bool | None = None
        category_id: int | None = None

    class CategoryRequest(BaseModel):
        name: str
        description: str = ""
        color: str = "blue"

    class CredentialRequest(BaseModel):
        id: str = "default"
        account_name: str = ""
        token: str = ""
        cookie: str = ""
        extra: dict[str, str] = {}
        expires_at: str | None = None

    class VerificationRequest(BaseModel):
        id: str
        kind: str = "manual"
        target: str = ""
        verify_url: str = ""
        message: str = ""

    class BlacklistRequest(BaseModel):
        account_id: str
        reason: str = ""

    class RateLimitRequest(BaseModel):
        per_minute: int | None = None
        min_interval_seconds: float | None = None

    @asynccontextmanager
    async def lifespan(app: Any) -> Any:
        tasks: list[asyncio.Task] = []
        if settings.background_polling:
            tasks.append(asyncio.create_task(_polling_loop(poller, settings.poll_interval_seconds)))
        if settings.credential_reminders:
            tasks.append(asyncio.create_task(_credential_reminder_loop(repo, notifier)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="wechat-rss-lite", version="0.2.0", lifespan=lifespan)

    def require_admin(authorization: str | None = Header(default=None)) -> None:
        if not settings.admin_token:
            return
        if authorization == f"Bearer {settings.admin_token}":
            return
        raise HTTPException(status_code=401, detail="Admin token required")

    def find_subscription(subscription_id: str) -> Subscription:
        subscription = next((item for item in repo.list_subscriptions() if item.id == subscription_id), None)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return subscription

    @app.get("/", response_class=HTMLResponse)
    @app.get("/admin", response_class=HTMLResponse)
    async def admin() -> str:
        return ADMIN_HTML

    @app.get("/health")
    async def health() -> dict[str, Any]:
        credential = repo.get_credential()
        database_ok = True
        try:
            repo.list_subscriptions()
        except Exception:
            database_ok = False
        return {
            "status": "ok" if database_ok else "degraded",
            "database": {"ok": database_ok},
            "proxy_pool": proxies.status(),
            "rate_limit": limiter.stats(),
            "credential": _credential_to_dict(credential) if credential else {
                "configured": False,
                "stored": False,
                "wechat_configured": False,
                "demo": False,
                "account_name": "",
                "source": "",
                "expires_at": None,
                "expired": False,
            },
        }

    @app.get("/stats")
    async def stats() -> dict[str, Any]:
        return {
            "rate_limit": limiter.stats(),
            "proxy_pool": proxies.status(),
            "poll_runs": [_poll_result_to_dict(result) for result in repo.latest_poll_results(limit=10)],
            "subscriptions": len(repo.list_subscriptions()),
            "categories": len(repo.list_categories()),
            "blacklist": len(repo.list_blacklist()),
            "pending_verifications": len(repo.list_verification_challenges(status="pending", limit=200)),
            "background_polling": settings.background_polling,
            "credential_reminders": settings.credential_reminders,
        }

    @app.get("/rate-limit")
    async def get_rate_limit() -> dict[str, Any]:
        return limiter.stats()

    @app.put("/rate-limit", dependencies=[Depends(require_admin)])
    async def update_rate_limit(request: RateLimitRequest) -> dict[str, Any]:
        limiter.configure(
            per_minute=request.per_minute,
            min_interval_seconds=request.min_interval_seconds,
        )
        return limiter.stats()

    @app.post("/login/sessions", dependencies=[Depends(require_admin)])
    async def create_login_session() -> dict[str, Any]:
        return _login_session_to_dict(await auth.create_login_session())

    @app.get("/login/sessions/{session_id}", dependencies=[Depends(require_admin)])
    async def poll_login_session(session_id: str) -> dict[str, Any]:
        return _login_session_to_dict(await auth.poll_login_session(session_id))

    @app.post("/login/sessions/{session_id}/complete", dependencies=[Depends(require_admin)])
    async def complete_login_session(session_id: str) -> dict[str, Any]:
        try:
            return _credential_to_dict(await auth.complete_login_session(session_id))
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/login/confirm/{session_id}", response_class=HTMLResponse)
    async def confirm_login_page(session_id: str) -> str:
        return f"""
        <!doctype html>
        <html lang="zh-CN">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>确认登录</title>
          <style>
            body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: system-ui, sans-serif; background: #f7f7f4; color: #1f2933; }}
            main {{ width: min(420px, calc(100vw - 32px)); background: white; border: 1px solid #deded8; border-radius: 8px; padding: 24px; }}
            button {{ padding: 12px 16px; border: 1px solid #1f2933; border-radius: 6px; background: #1f2933; color: white; font: inherit; }}
          </style>
        </head>
        <body>
          <main>
            <h1>确认登录</h1>
            <p>确认后，当前后台会话将获得本地管理凭证。</p>
            <form method="post" action="/login/confirm/{session_id}">
              <button type="submit">确认登录</button>
            </form>
          </main>
        </body>
        </html>
        """

    @app.post("/login/confirm/{session_id}", response_class=HTMLResponse)
    async def confirm_login(session_id: str) -> str:
        session = await auth.confirm_login_session(session_id)
        return f"""
        <!doctype html>
        <html lang="zh-CN">
        <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>登录已确认</title></head>
        <body style="font-family: system-ui, sans-serif; padding: 24px;">
          <h1>{session.message}</h1>
          <p>现在可以回到管理后台点击“完成登录”。</p>
        </body>
        </html>
        """

    @app.post("/credentials", dependencies=[Depends(require_admin)])
    async def save_credential(request: CredentialRequest) -> dict[str, Any]:
        from datetime import datetime

        credential = Credential(
            id=request.id,
            account_name=request.account_name,
            token=request.token,
            cookie=request.cookie,
            extra=request.extra,
            expires_at=datetime.fromisoformat(request.expires_at) if request.expires_at else None,
        )
        repo.save_credential(credential)
        return _credential_to_dict(credential)

    @app.get("/credentials/{credential_id}", dependencies=[Depends(require_admin)])
    async def get_credential(credential_id: str = "default") -> dict[str, Any]:
        credential = repo.get_credential(credential_id)
        if not credential:
            raise HTTPException(status_code=404, detail="Credential not found")
        return _credential_to_dict(credential)

    @app.delete("/credentials/{credential_id}", dependencies=[Depends(require_admin)])
    async def delete_credential(credential_id: str = "default") -> dict[str, bool]:
        repo.delete_credential(credential_id)
        return {"deleted": True}

    @app.post("/credentials/{credential_id}/validate", dependencies=[Depends(require_admin)])
    async def validate_credential(credential_id: str = "default") -> dict[str, Any]:
        credential = repo.get_credential(credential_id)
        if not credential:
            raise HTTPException(status_code=404, detail="Credential not found")
        result = await validate_wechat_credential(
            credential,
            timeout=settings.request_timeout_seconds,
        )
        if result.get("valid") and result.get("account_name") and result["account_name"] != credential.account_name:
            credential = Credential(
                id=credential.id,
                account_name=str(result["account_name"]),
                token=credential.token,
                cookie=credential.cookie,
                extra={
                    **credential.extra,
                    "provider": credential.extra.get("provider", "wechat_mp"),
                    "username": str(result.get("username", "")),
                },
                created_at=credential.created_at,
                expires_at=credential.expires_at,
            )
            repo.save_credential(credential)
        return result

    @app.post("/articles/parse")
    async def parse_article(request: ParseRequest) -> dict[str, Any]:
        try:
            article = await article_client.fetch_article(str(request.url))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _article_to_dict(article)

    @app.get("/accounts/search")
    async def search_accounts(query: str, limit: int = Query(default=10, ge=1, le=50)) -> list[dict[str, Any]]:
        return [
            _account_to_dict(account)
            for account in await accounts.search_accounts(query, limit=limit)
        ]

    @app.get("/accounts/{account_id}/articles")
    async def list_account_articles(
        account_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        keyword: str = "",
    ) -> list[dict[str, Any]]:
        summaries = await accounts.list_articles(account_id, offset=offset, limit=limit, keyword=keyword)
        return [summary.__dict__ for summary in summaries]

    @app.get("/accounts/{account_id}/info")
    async def account_info(account_id: str) -> dict[str, Any]:
        provider_method = getattr(accounts, "account_info", None)
        if provider_method:
            return await provider_method(account_id)
        return {"id": account_id, "available": False, "message": "Account info provider is not configured."}

    @app.post("/subscriptions", dependencies=[Depends(require_admin)])
    async def subscribe(request: SubscriptionRequest) -> dict[str, Any]:
        subscription_id = request.id.strip()
        title = request.title.strip() or subscription_id
        if not subscription_id:
            raise HTTPException(status_code=400, detail="Subscription id is required")
        subscription = Subscription(
            id=subscription_id,
            title=title,
            account_id=request.account_id or request.id,
            source_url=request.source_url,
            avatar_url=request.avatar_url,
            description=request.description,
            category_id=request.category_id,
            enabled=request.enabled,
        )
        repo.add_subscription(subscription)
        return _subscription_to_dict(subscription, settings=settings)

    @app.get("/subscriptions")
    async def list_subscriptions() -> list[dict[str, Any]]:
        return [_subscription_to_dict(subscription, settings=settings) for subscription in repo.list_subscriptions()]

    @app.patch("/subscriptions/{subscription_id}", dependencies=[Depends(require_admin)])
    async def update_subscription(subscription_id: str, request: SubscriptionUpdateRequest) -> dict[str, Any]:
        subscription = find_subscription(subscription_id)
        if request.enabled is None:
            if request.category_id is None:
                return _subscription_to_dict(subscription, settings=settings)
            updated = repo.set_subscription_category(subscription_id, request.category_id)
        else:
            updated = repo.set_subscription_enabled(subscription_id, request.enabled)
            if updated and request.category_id is not None:
                updated = repo.set_subscription_category(subscription_id, request.category_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return _subscription_to_dict(updated, settings=settings)

    @app.get("/categories")
    async def list_categories() -> list[dict[str, Any]]:
        return [_category_to_dict(category, repo=repo) for category in repo.list_categories()]

    @app.post("/categories", dependencies=[Depends(require_admin)])
    async def create_category(request: CategoryRequest) -> dict[str, Any]:
        try:
            category = repo.create_category(
                Category(name=request.name, description=request.description, color=request.color)
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _category_to_dict(category, repo=repo)

    @app.patch("/categories/{category_id}", dependencies=[Depends(require_admin)])
    async def update_category(category_id: int, request: CategoryRequest) -> dict[str, Any]:
        category = repo.update_category(
            category_id,
            name=request.name,
            description=request.description,
            color=request.color,
        )
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        return _category_to_dict(category, repo=repo)

    @app.delete("/categories/{category_id}", dependencies=[Depends(require_admin)])
    async def delete_category(category_id: int) -> dict[str, bool]:
        repo.delete_category(category_id)
        return {"deleted": True}

    @app.post("/subscriptions/import", dependencies=[Depends(require_admin)])
    async def import_subscriptions(
        text: str = Form(default=""),
        file: UploadFile | None = File(default=None),
    ) -> dict[str, Any]:
        from .importer import parse_subscription_import

        filename = file.filename if file else ""
        content = await file.read() if file else None
        try:
            entries = parse_subscription_import(text=text, filename=filename, content=content)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        imported: list[dict[str, Any]] = []
        for entry in entries:
            subscription = Subscription(id=entry.id, title=entry.title, account_id=entry.id)
            repo.add_subscription(subscription)
            imported.append(_subscription_to_dict(subscription, settings=settings))
        return {"imported": len(imported), "items": imported}

    @app.delete("/subscriptions/{subscription_id}", dependencies=[Depends(require_admin)])
    async def delete_subscription(subscription_id: str) -> dict[str, bool]:
        repo.delete_subscription(subscription_id)
        return {"deleted": True}

    @app.get("/verifications")
    async def list_verifications(
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return [
            _verification_to_dict(challenge)
            for challenge in repo.list_verification_challenges(status=status, limit=limit)
        ]

    @app.post("/verifications", dependencies=[Depends(require_admin)])
    async def create_verification(request: VerificationRequest) -> dict[str, Any]:
        challenge = VerificationChallenge(
            id=request.id,
            kind=request.kind,
            target=request.target,
            verify_url=request.verify_url,
            message=request.message,
        )
        repo.add_verification_challenge(challenge)
        return _verification_to_dict(challenge)

    @app.post("/verifications/{challenge_id}/resolve", dependencies=[Depends(require_admin)])
    async def resolve_verification(challenge_id: str) -> dict[str, Any]:
        challenge = repo.resolve_verification_challenge(challenge_id)
        if not challenge:
            raise HTTPException(status_code=404, detail="Verification challenge not found")
        return _verification_to_dict(challenge)

    @app.get("/blacklist")
    async def list_blacklist() -> list[dict[str, Any]]:
        return [_blacklist_to_dict(entry) for entry in repo.list_blacklist()]

    @app.post("/blacklist", dependencies=[Depends(require_admin)])
    async def add_blacklist_entry(request: BlacklistRequest) -> dict[str, Any]:
        entry = BlacklistEntry(account_id=request.account_id, reason=request.reason)
        repo.add_blacklist_entry(entry)
        return _blacklist_to_dict(entry)

    @app.delete("/blacklist/{account_id}", dependencies=[Depends(require_admin)])
    async def remove_blacklist_entry(account_id: str) -> dict[str, bool]:
        repo.remove_blacklist_entry(account_id)
        return {"deleted": True}

    @app.get("/subscriptions/{subscription_id}/articles")
    async def subscription_articles(
        subscription_id: str,
        limit: int = Query(default=20, ge=1, le=200),
        source: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        find_subscription(subscription_id)
        return [
            _article_to_dict(article)
            for article in repo.recent_articles(subscription_id=subscription_id, limit=limit, source=source)
        ]

    @app.post("/subscriptions/{subscription_id}/poll", dependencies=[Depends(require_admin)])
    async def poll_subscription(subscription_id: str, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        subscription = find_subscription(subscription_id)
        return _poll_result_to_dict(await poller.poll_subscription(subscription, limit=limit))

    @app.post("/subscriptions/{subscription_id}/history", dependencies=[Depends(require_admin)])
    async def fetch_subscription_history(
        subscription_id: str,
        pages: int = Query(default=5, ge=1, le=50),
        page_size: int = Query(default=20, ge=1, le=100),
        keyword: str = "",
    ) -> dict[str, Any]:
        subscription = find_subscription(subscription_id)
        result = await poller.fetch_history(
            subscription,
            pages=pages,
            page_size=page_size,
            keyword=keyword,
        )
        return _poll_result_to_dict(result)

    @app.post("/poll", dependencies=[Depends(require_admin)])
    async def poll_all(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return [_poll_result_to_dict(result) for result in await poller.poll_all(limit_per_subscription=limit)]

    @app.get("/poll/runs")
    async def poll_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return [_poll_result_to_dict(result) for result in repo.latest_poll_results(limit=limit)]

    @app.get("/feeds/{subscription_id}.xml")
    @app.get("/feeds/{subscription_id}.rss")
    async def feed(
        subscription_id: str,
        limit: int = Query(default=20, ge=1, le=100),
        source: str | None = Query(default=None),
    ) -> Response:
        if subscription_id == "all":
            xml = render_rss(
                title="WeChat RSS - 全部订阅",
                link=f"{settings.site_url}/feeds/all.rss",
                description="Aggregated RSS feed for all subscriptions",
                articles=repo.recent_articles(limit=limit, source=source or "poll"),
                image_proxy_base=f"{settings.site_url}/image",
            )
            return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
        subscription = find_subscription(subscription_id)
        xml = render_rss(
            title=subscription.title,
            link=f"{settings.site_url}/feeds/{subscription.id}.rss",
            description=f"RSS feed for {subscription.title}",
            articles=repo.recent_articles(subscription_id=subscription.id, limit=limit, source=source),
            image_proxy_base=f"{settings.site_url}/image",
        )
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    @app.get("/feeds/{subscription_id}/history.rss")
    async def history_feed(subscription_id: str, limit: int = Query(default=100, ge=1, le=500)) -> Response:
        subscription = find_subscription(subscription_id)
        xml = render_rss(
            title=f"{subscription.title} - 历史文章",
            link=f"{settings.site_url}/feeds/{subscription.id}/history.rss",
            description=f"Historical RSS feed for {subscription.title}",
            articles=repo.recent_articles(subscription_id=subscription.id, limit=limit, source="history"),
            image_proxy_base=f"{settings.site_url}/image",
        )
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    @app.get("/feeds/all.rss")
    async def all_feed(limit: int = Query(default=100, ge=1, le=500)) -> Response:
        xml = render_rss(
            title="WeChat RSS - 全部订阅",
            link=f"{settings.site_url}/feeds/all.rss",
            description="Aggregated RSS feed for all subscriptions",
            articles=repo.recent_articles(limit=limit, source="poll"),
            image_proxy_base=f"{settings.site_url}/image",
        )
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    @app.get("/feeds/categories/{category_id}.rss")
    async def category_feed(category_id: int, limit: int = Query(default=100, ge=1, le=500)) -> Response:
        category = next((item for item in repo.list_categories() if item.id == category_id), None)
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        xml = render_rss(
            title=f"WeChat RSS - {category.name}",
            link=f"{settings.site_url}/feeds/categories/{category_id}.rss",
            description=category.description or f"RSS feed for category {category.name}",
            articles=repo.recent_articles(limit=limit, source="poll", category_id=category_id),
            image_proxy_base=f"{settings.site_url}/image",
        )
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    @app.get("/subscriptions/export")
    async def export_subscriptions(format: str = Query(default="opml", pattern="^(opml|csv)$")) -> Response:
        subscriptions = repo.list_subscriptions()
        if format == "csv":
            return _subscriptions_csv(subscriptions, settings=settings)
        return _subscriptions_opml(subscriptions, settings=settings)

    @app.post("/rss/render")
    async def rss(request: RssRequest) -> dict[str, str]:
        articles = [Article(**item) for item in request.articles]
        return {
            "rss": render_rss(
                title=request.title,
                link=str(request.link),
                description=request.description,
                articles=articles,
            )
        }

    @app.get("/image")
    async def image(url: str) -> Response:
        try:
            body, content_type = await images.fetch(url)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(content=body, media_type=content_type)

    return app


def _build_login_provider(settings: Settings) -> LoginProvider:
    provider = settings.login_provider.strip().lower()
    if provider == "local":
        return LocalQrLoginProvider(base_url=settings.site_url)
    if provider in {"manual", "disabled", "none"}:
        return ManualLoginProvider()
    return WeChatMpLoginProvider(timeout=settings.request_timeout_seconds)


def _article_to_dict(article: Article) -> dict[str, Any]:
    return {
        "url": article.url,
        "title": article.title,
        "author": article.author,
        "account_name": article.account_name,
        "summary": article.summary,
        "content_html": article.content_html,
        "text": article.text,
        "content_type": article.content_type,
        "unavailable_reason": article.unavailable_reason,
        "status": article.status,
        "source": article.source,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "images": [{"url": image.url, "alt": image.alt} for image in article.images],
    }


def _account_to_dict(account: Any) -> dict[str, Any]:
    avatar_url = account.avatar_url
    return {
        "id": account.id,
        "name": account.name,
        "alias": account.alias,
        "avatar_url": f"/image?url={quote(avatar_url, safe='')}" if avatar_url else "",
        "raw_avatar_url": avatar_url,
        "description": account.description,
    }


def _subscription_to_dict(subscription: Subscription, *, settings: Settings | None = None) -> dict[str, Any]:
    feed_url = f"{settings.site_url}/feeds/{subscription.id}.rss" if settings else f"/feeds/{subscription.id}.rss"
    return {
        "id": subscription.id,
        "title": subscription.title,
        "account_id": subscription.account_id,
        "source_url": subscription.source_url,
        "avatar_url": subscription.avatar_url,
        "description": subscription.description,
        "category_id": subscription.category_id,
        "feed_url": feed_url,
        "history_feed_url": f"{settings.site_url}/feeds/{subscription.id}/history.rss" if settings else f"/feeds/{subscription.id}/history.rss",
        "enabled": subscription.enabled,
        "created_at": subscription.created_at.isoformat(),
        "updated_at": subscription.updated_at.isoformat(),
    }


def _category_to_dict(category: Category, *, repo: SQLiteRepository) -> dict[str, Any]:
    return {
        "id": category.id,
        "name": category.name,
        "description": category.description,
        "color": category.color,
        "sort_order": category.sort_order,
        "subscription_count": sum(1 for item in repo.list_subscriptions() if item.category_id == category.id),
        "created_at": category.created_at.isoformat(),
    }


def _credential_to_dict(credential: Credential) -> dict[str, Any]:
    source = credential.extra.get("provider", "")
    demo = source in {"local_qr", "manual"} or credential.account_name in {"manual", "local-admin"}
    stored = bool(credential.token or credential.cookie or credential.extra)
    wechat_configured = stored and not demo and not credential.is_expired
    return {
        "id": credential.id,
        "account_name": credential.account_name,
        "configured": wechat_configured,
        "stored": stored,
        "wechat_configured": wechat_configured,
        "demo": demo,
        "source": source or ("local" if demo else ""),
        "expires_at": credential.expires_at.isoformat() if credential.expires_at else None,
        "expired": credential.is_expired,
    }


def _login_session_to_dict(session: Any) -> dict[str, Any]:
    return {
        "id": session.id,
        "qrcode_url": session.qrcode_url,
        "status": getattr(session.status, "value", session.status),
        "message": session.message,
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
    }


def _poll_result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "subscription_id": result.subscription_id,
        "fetched": result.fetched,
        "stored": result.stored,
        "failed": result.failed,
        "message": result.message,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
    }


def _verification_to_dict(challenge: VerificationChallenge) -> dict[str, Any]:
    return {
        "id": challenge.id,
        "kind": challenge.kind,
        "target": challenge.target,
        "verify_url": challenge.verify_url,
        "status": challenge.status,
        "message": challenge.message,
        "created_at": challenge.created_at.isoformat(),
        "resolved_at": challenge.resolved_at.isoformat() if challenge.resolved_at else None,
    }


def _blacklist_to_dict(entry: BlacklistEntry) -> dict[str, Any]:
    return {
        "account_id": entry.account_id,
        "reason": entry.reason,
        "created_at": entry.created_at.isoformat(),
    }


def _subscriptions_csv(subscriptions: list[Subscription], *, settings: Settings) -> Any:
    from fastapi import Response

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["Title", "Account ID", "RSS URL", "History RSS URL", "Category ID", "Enabled"])
    for subscription in subscriptions:
        writer.writerow(
            [
                subscription.title,
                subscription.account_id or subscription.id,
                f"{settings.site_url}/feeds/{subscription.id}.rss",
                f"{settings.site_url}/feeds/{subscription.id}/history.rss",
                subscription.category_id or "",
                "yes" if subscription.enabled else "no",
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="wechat_rss_subscriptions.csv"'},
    )


def _subscriptions_opml(subscriptions: list[Subscription], *, settings: Settings) -> Any:
    from fastapi import Response

    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = "WeChat RSS Subscriptions"
    body = ET.SubElement(opml, "body")
    group = ET.SubElement(body, "outline", text="WeChat RSS", title="WeChat RSS")
    for subscription in subscriptions:
        title = subscription.title or subscription.id
        ET.SubElement(
            group,
            "outline",
            {
                "type": "rss",
                "text": title,
                "title": title,
                "xmlUrl": f"{settings.site_url}/feeds/{subscription.id}.rss",
                "htmlUrl": subscription.source_url or "https://mp.weixin.qq.com",
                "description": subscription.description or f"{title} - WeChat RSS",
            },
        )
    content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(opml, encoding="unicode")
    return Response(
        content=content,
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="wechat_rss_subscriptions.opml"'},
    )


async def _polling_loop(poller: RssPoller, interval_seconds: int) -> None:
    interval = max(interval_seconds, 60)
    while True:
        await asyncio.sleep(interval)
        try:
            await poller.poll_all()
        except Exception:
            continue


async def _credential_reminder_loop(repo: SQLiteRepository, notifier: WebhookNotifier) -> None:
    sent: set[str] = set()
    while True:
        credential = repo.get_credential()
        if credential and credential.expires_at:
            now = datetime.now(timezone.utc)
            remaining = (credential.expires_at.astimezone(timezone.utc) - now).total_seconds()
            for label, threshold in (("expired", 0), ("6h", 6 * 3600), ("24h", 24 * 3600)):
                key = f"{credential.id}:{label}:{credential.expires_at.isoformat()}"
                if key in sent:
                    continue
                if (label == "expired" and remaining <= 0) or (label != "expired" and 0 < remaining <= threshold):
                    await notifier.send(
                        NotificationEvent(
                            kind="credential.expiry_reminder",
                            message=f"Credential {label} reminder for {credential.account_name or credential.id}",
                            target=credential.id,
                        )
                    )
                    sent.add(key)
        await asyncio.sleep(3600)
