from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from ..adapters import AccountProvider, LoginProvider
from ..admin import ADMIN_HTML
from ..auth import AuthManager
from ..client import WeChatArticleClient, _validate_wechat_article_url
from ..config import Settings
from ..exceptions import FetchError
from ..image_proxy import ImageProxy
from ..models import Article, BlacklistEntry, Category, Credential, Subscription, VerificationChallenge
from ..poller import RssPoller
from ..proxy import ProxyPool
from ..rate_limit import AsyncRateLimiter
from ..rss import render_rss
from ..storage import SQLiteRepository
from ..wechat_account import WeChatMpAccountProvider
from ..webhook import WebhookNotifier
from ..wechat_login import validate_wechat_credential

from .context import ApiContext
from .deps import build_admin_dep, build_rss_dep, make_find_subscription
from .factory import build_article_client, build_login_provider, image_proxy_base as resolve_image_proxy_base
from .reader import build_reader_html
from .refresh import refresh_article_targets
from .schemas import (
    BlacklistRequest,
    CategoryRequest,
    CredentialRequest,
    ParseRequest,
    RateLimitRequest,
    RssRequest,
    SubscriptionRequest,
    SubscriptionUpdateRequest,
    VerificationRequest,
)
from .serializers import (
    account_to_dict,
    article_to_dict,
    blacklist_to_dict,
    category_to_dict,
    credential_reminder_loop,
    credential_to_dict,
    login_session_to_dict,
    poll_result_to_dict,
    polling_loop,
    public_feed_url,
    subscription_to_dict,
    subscriptions_csv,
    subscriptions_opml,
    verification_to_dict,
)

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
    site_image_proxy_base = resolve_image_proxy_base(settings)
    api_image_proxy_base = "/image"
    repo = repository or SQLiteRepository(settings.db_path)
    proxies = ProxyPool(settings.proxy_urls)
    limiter = AsyncRateLimiter(
        per_minute=settings.rate_limit_per_minute,
        min_interval_seconds=settings.article_interval_seconds,
    )
    notifier = WebhookNotifier(settings.webhook_url)
    article_client = article_client or build_article_client(settings, repo, proxies, limiter)
    accounts = account_provider or WeChatMpAccountProvider(
        repository=repo,
        timeout=settings.request_timeout_seconds,
    )
    login_provider = login_provider or build_login_provider(settings)
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
        credential_getter=repo.get_credential,
    )

    ctx = ApiContext(
        settings=settings,
        repo=repo,
        proxies=proxies,
        limiter=limiter,
        notifier=notifier,
        article_client=article_client,
        accounts=accounts,
        login_provider=login_provider,
        auth=auth,
        poller=poller,
        images=images,
        image_proxy_base=site_image_proxy_base,
        api_image_proxy_base=api_image_proxy_base,
    )

    admin_dep = build_admin_dep(settings)
    rss_dep = build_rss_dep(settings)

    @asynccontextmanager
    async def lifespan(app: Any) -> Any:
        tasks: list[asyncio.Task] = []
        if settings.background_polling:
            tasks.append(asyncio.create_task(polling_loop(poller, settings.poll_interval_seconds)))
        if settings.credential_reminders:
            tasks.append(asyncio.create_task(credential_reminder_loop(repo, notifier)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="wechat-rss-lite", version="0.2.0", lifespan=lifespan)

    find_subscription = make_find_subscription(repo)

    def subscription_payload(subscription: Subscription, *, stats_map: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
        article_stats = (stats_map or repo.subscription_article_stats()).get(subscription.id)
        return subscription_to_dict(subscription, settings=settings, article_stats=article_stats)

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
            "credential": credential_to_dict(credential) if credential else {
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

    @app.get("/stats", dependencies=[Depends(admin_dep)])
    async def stats() -> dict[str, Any]:
        return {
            "rate_limit": limiter.stats(),
            "proxy_pool": proxies.status(),
            "poll_runs": [poll_result_to_dict(result) for result in repo.latest_poll_results(limit=10)],
            "subscriptions": len(repo.list_subscriptions()),
            "categories": len(repo.list_categories()),
            "blacklist": len(repo.list_blacklist()),
            "pending_verifications": len(repo.list_verification_challenges(status="pending", limit=200)),
            "background_polling": settings.background_polling,
            "credential_reminders": settings.credential_reminders,
        }

    @app.get("/rate-limit", dependencies=[Depends(admin_dep)])
    async def get_rate_limit() -> dict[str, Any]:
        return limiter.stats()

    @app.put("/rate-limit", dependencies=[Depends(admin_dep)])
    async def update_rate_limit(request: RateLimitRequest) -> dict[str, Any]:
        limiter.configure(
            per_minute=request.per_minute,
            min_interval_seconds=request.min_interval_seconds,
        )
        return limiter.stats()

    @app.post("/login/sessions", dependencies=[Depends(admin_dep)])
    async def create_login_session() -> dict[str, Any]:
        try:
            return login_session_to_dict(await auth.create_login_session())
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/login/sessions/{session_id}", dependencies=[Depends(admin_dep)])
    async def poll_login_session(session_id: str) -> dict[str, Any]:
        return login_session_to_dict(await auth.poll_login_session(session_id))

    @app.post("/login/sessions/{session_id}/complete", dependencies=[Depends(admin_dep)])
    async def complete_login_session(session_id: str) -> dict[str, Any]:
        try:
            return credential_to_dict(await auth.complete_login_session(session_id))
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

    @app.post("/credentials", dependencies=[Depends(admin_dep)])
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
        return credential_to_dict(credential)

    @app.get("/credentials/{credential_id}", dependencies=[Depends(admin_dep)])
    async def get_credential(credential_id: str = "default") -> dict[str, Any]:
        credential = repo.get_credential(credential_id)
        if not credential:
            raise HTTPException(status_code=404, detail="Credential not found")
        return credential_to_dict(credential)

    @app.delete("/credentials/{credential_id}", dependencies=[Depends(admin_dep)])
    async def delete_credential(credential_id: str = "default") -> dict[str, bool]:
        repo.delete_credential(credential_id)
        return {"deleted": True}

    @app.post("/credentials/{credential_id}/validate", dependencies=[Depends(admin_dep)])
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

    @app.post("/articles/parse", dependencies=[Depends(admin_dep)])
    async def parse_article(request: ParseRequest) -> dict[str, Any]:
        try:
            _validate_wechat_article_url(str(request.url))
            article = await article_client.fetch_article(str(request.url))
        except FetchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return article_to_dict(article, image_proxy_base=api_image_proxy_base)

    @app.get("/articles", dependencies=[Depends(admin_dep)])
    async def list_downloaded_articles(
        subscription_id: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        source: str | None = Query(default=None),
        status: str | None = Query(default="fetched"),
    ) -> list[dict[str, Any]]:
        if subscription_id:
            find_subscription(subscription_id)
        return [
            article_to_dict(article, image_proxy_base=api_image_proxy_base)
            for article in repo.recent_articles(
                subscription_id=subscription_id,
                limit=limit,
                source=source,
                status=status or None,
            )
        ]

    @app.get("/articles/read", dependencies=[Depends(admin_dep)])
    async def read_downloaded_article(url: str) -> dict[str, Any]:
        article = repo.get_article(url)
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        return article_to_dict(article, image_proxy_base=api_image_proxy_base)

    @app.get("/articles/read/html", response_class=HTMLResponse, dependencies=[Depends(admin_dep)])
    async def read_downloaded_article_html(url: str) -> HTMLResponse:
        article = repo.get_article(url)
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        data = article_to_dict(article, image_proxy_base=api_image_proxy_base)
        return HTMLResponse(build_reader_html(data))

    @app.post("/articles/refresh", dependencies=[Depends(admin_dep)])
    async def refresh_downloaded_articles(
        url: str | None = Query(default=None),
        subscription_id: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1, le=500),
    ) -> dict[str, Any]:
        if url:
            _validate_wechat_article_url(url)
        if subscription_id:
            find_subscription(subscription_id)
        batch_limit = settings.refresh_batch_limit if limit is None else limit
        targets = repo.article_refresh_targets(
            url=url,
            subscription_id=subscription_id,
            status="fetched",
            limit=None if url else batch_limit,
        )
        if url and not targets:
            raise HTTPException(status_code=404, detail="Article not found")
        result = await refresh_article_targets(ctx, targets)
        if not url:
            result["batch_limit"] = batch_limit
        return result

    @app.get("/accounts/search", dependencies=[Depends(admin_dep)])
    async def search_accounts(query: str, limit: int = Query(default=10, ge=1, le=50)) -> list[dict[str, Any]]:
        return [
            account_to_dict(account)
            for account in await accounts.search_accounts(query, limit=limit)
        ]

    @app.get("/accounts/{account_id}/articles", dependencies=[Depends(admin_dep)])
    async def list_account_articles(
        account_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        keyword: str = "",
    ) -> list[dict[str, Any]]:
        summaries = await accounts.list_articles(account_id, offset=offset, limit=limit, keyword=keyword)
        return [summary.__dict__ for summary in summaries]

    @app.get("/accounts/{account_id}/info", dependencies=[Depends(admin_dep)])
    async def account_info(account_id: str) -> dict[str, Any]:
        provider_method = getattr(accounts, "account_info", None)
        if provider_method:
            return await provider_method(account_id)
        return {"id": account_id, "available": False, "message": "Account info provider is not configured."}

    @app.post("/subscriptions", dependencies=[Depends(admin_dep)])
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
        return subscription_payload(subscription)

    @app.get("/subscriptions", dependencies=[Depends(admin_dep)])
    async def list_subscriptions() -> list[dict[str, Any]]:
        stats_map = repo.subscription_article_stats()
        return [
            subscription_payload(subscription, stats_map=stats_map)
            for subscription in repo.list_subscriptions()
        ]

    @app.patch("/subscriptions/{subscription_id}", dependencies=[Depends(admin_dep)])
    async def update_subscription(subscription_id: str, request: SubscriptionUpdateRequest) -> dict[str, Any]:
        subscription = find_subscription(subscription_id)
        if request.enabled is None:
            if request.category_id is None:
                return subscription_payload(subscription)
            updated = repo.set_subscription_category(subscription_id, request.category_id)
        else:
            updated = repo.set_subscription_enabled(subscription_id, request.enabled)
            if updated and request.category_id is not None:
                updated = repo.set_subscription_category(subscription_id, request.category_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return subscription_payload(updated)

    @app.get("/categories", dependencies=[Depends(admin_dep)])
    async def list_categories() -> list[dict[str, Any]]:
        return [category_to_dict(category, repo=repo) for category in repo.list_categories()]

    @app.post("/categories", dependencies=[Depends(admin_dep)])
    async def create_category(request: CategoryRequest) -> dict[str, Any]:
        try:
            category = repo.create_category(
                Category(name=request.name, description=request.description, color=request.color)
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return category_to_dict(category, repo=repo)

    @app.patch("/categories/{category_id}", dependencies=[Depends(admin_dep)])
    async def update_category(category_id: int, request: CategoryRequest) -> dict[str, Any]:
        category = repo.update_category(
            category_id,
            name=request.name,
            description=request.description,
            color=request.color,
        )
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        return category_to_dict(category, repo=repo)

    @app.delete("/categories/{category_id}", dependencies=[Depends(admin_dep)])
    async def delete_category(category_id: int) -> dict[str, bool]:
        repo.delete_category(category_id)
        return {"deleted": True}

    @app.post("/subscriptions/import", dependencies=[Depends(admin_dep)])
    async def import_subscriptions(
        text: str = Form(default=""),
        file: UploadFile | None = File(default=None),
    ) -> dict[str, Any]:
        from ..importer import parse_subscription_import

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
            imported.append(subscription_payload(subscription))
        return {"imported": len(imported), "items": imported}

    @app.delete("/subscriptions/{subscription_id}", dependencies=[Depends(admin_dep)])
    async def delete_subscription(subscription_id: str) -> dict[str, bool]:
        repo.delete_subscription(subscription_id)
        return {"deleted": True}

    @app.get("/verifications", dependencies=[Depends(admin_dep)])
    async def list_verifications(
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return [
            verification_to_dict(challenge)
            for challenge in repo.list_verification_challenges(status=status, limit=limit)
        ]

    @app.post("/verifications", dependencies=[Depends(admin_dep)])
    async def create_verification(request: VerificationRequest) -> dict[str, Any]:
        challenge = VerificationChallenge(
            id=request.id,
            kind=request.kind,
            target=request.target,
            verify_url=request.verify_url,
            message=request.message,
        )
        repo.add_verification_challenge(challenge)
        return verification_to_dict(challenge)

    @app.post("/verifications/{challenge_id}/resolve", dependencies=[Depends(admin_dep)])
    async def resolve_verification(challenge_id: str) -> dict[str, Any]:
        challenge = repo.resolve_verification_challenge(challenge_id)
        if not challenge:
            raise HTTPException(status_code=404, detail="Verification challenge not found")
        return verification_to_dict(challenge)

    @app.get("/blacklist", dependencies=[Depends(admin_dep)])
    async def list_blacklist() -> list[dict[str, Any]]:
        return [blacklist_to_dict(entry) for entry in repo.list_blacklist()]

    @app.post("/blacklist", dependencies=[Depends(admin_dep)])
    async def add_blacklist_entry(request: BlacklistRequest) -> dict[str, Any]:
        entry = BlacklistEntry(account_id=request.account_id, reason=request.reason)
        repo.add_blacklist_entry(entry)
        return blacklist_to_dict(entry)

    @app.delete("/blacklist/{account_id}", dependencies=[Depends(admin_dep)])
    async def remove_blacklist_entry(account_id: str) -> dict[str, bool]:
        repo.remove_blacklist_entry(account_id)
        return {"deleted": True}

    @app.get("/subscriptions/{subscription_id}/articles", dependencies=[Depends(admin_dep)])
    async def subscription_articles(
        subscription_id: str,
        limit: int = Query(default=20, ge=1, le=200),
        source: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        find_subscription(subscription_id)
        return [
            article_to_dict(article, image_proxy_base=api_image_proxy_base)
            for article in repo.recent_articles(subscription_id=subscription_id, limit=limit, source=source)
        ]

    @app.post("/subscriptions/{subscription_id}/articles/refresh", dependencies=[Depends(admin_dep)])
    async def refresh_subscription_articles(
        subscription_id: str,
        limit: int | None = Query(default=None, ge=1, le=500),
    ) -> dict[str, Any]:
        find_subscription(subscription_id)
        batch_limit = settings.refresh_batch_limit if limit is None else limit
        targets = repo.article_refresh_targets(
            subscription_id=subscription_id,
            status="fetched",
            limit=batch_limit,
        )
        result = await refresh_article_targets(ctx, targets)
        result["batch_limit"] = batch_limit
        return result

    @app.post("/subscriptions/{subscription_id}/poll", dependencies=[Depends(admin_dep)])
    async def poll_subscription(subscription_id: str, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        subscription = find_subscription(subscription_id)
        return poll_result_to_dict(await poller.poll_subscription(subscription, limit=limit))

    @app.post("/subscriptions/{subscription_id}/history", dependencies=[Depends(admin_dep)])
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
        return poll_result_to_dict(result)

    @app.post("/poll", dependencies=[Depends(admin_dep)])
    async def poll_all(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return [poll_result_to_dict(result) for result in await poller.poll_all(limit_per_subscription=limit)]

    @app.get("/poll/runs", dependencies=[Depends(admin_dep)])
    async def poll_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return [poll_result_to_dict(result) for result in repo.latest_poll_results(limit=limit)]

    @app.get("/feeds/{subscription_id}.xml", dependencies=[Depends(rss_dep)])
    @app.get("/feeds/{subscription_id}.rss", dependencies=[Depends(rss_dep)])
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
            articles=repo.recent_articles(subscription_id=subscription.id, limit=limit, source=source or "poll"),
            image_proxy_base=f"{settings.site_url}/image",
        )
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    @app.get("/feeds/{subscription_id}/history.rss", dependencies=[Depends(rss_dep)])
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

    @app.get("/feeds/all.rss", dependencies=[Depends(rss_dep)])
    async def all_feed(limit: int = Query(default=100, ge=1, le=500)) -> Response:
        xml = render_rss(
            title="WeChat RSS - 全部订阅",
            link=f"{settings.site_url}/feeds/all.rss",
            description="Aggregated RSS feed for all subscriptions",
            articles=repo.recent_articles(limit=limit, source="poll"),
            image_proxy_base=f"{settings.site_url}/image",
        )
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    @app.get("/feeds/categories/{category_id}.rss", dependencies=[Depends(rss_dep)])
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

    @app.get("/subscriptions/export", dependencies=[Depends(admin_dep)])
    async def export_subscriptions(format: str = Query(default="opml", pattern="^(opml|csv)$")) -> Response:
        subscriptions = repo.list_subscriptions()
        if format == "csv":
            return subscriptions_csv(subscriptions, settings=settings)
        return subscriptions_opml(subscriptions, settings=settings)

    @app.post("/rss/render", dependencies=[Depends(admin_dep)])
    async def rss(request: RssRequest) -> dict[str, str]:
        articles = [Article(**item) for item in request.articles]
        return {
            "rss": render_rss(
                title=request.title,
                link=str(request.link),
                description=request.description,
                articles=articles,
                image_proxy_base=site_image_proxy_base,
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

