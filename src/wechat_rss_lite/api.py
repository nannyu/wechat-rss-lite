from typing import Any

from .adapters import AccountProvider, EmptyAccountProvider, LoginProvider
from .admin import ADMIN_HTML
from .auth import AuthManager
from .client import WeChatArticleClient
from .config import Settings
from .image_proxy import ImageProxy
from .models import Article, Credential, Subscription
from .poller import RssPoller
from .proxy import ProxyPool
from .rate_limit import AsyncRateLimiter
from .rss import render_rss
from .storage import SQLiteRepository
from .webhook import WebhookNotifier


def create_app(
    *,
    settings: Settings | None = None,
    repository: SQLiteRepository | None = None,
    account_provider: AccountProvider | None = None,
    login_provider: LoginProvider | None = None,
) -> Any:
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
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
    article_client = WeChatArticleClient(
        timeout=settings.request_timeout_seconds,
        retries=settings.request_retries,
        proxy_pool=proxies,
        rate_limiter=limiter,
    )
    accounts = account_provider or EmptyAccountProvider()
    auth = AuthManager(repository=repo, login_provider=login_provider, notifier=notifier)
    poller = RssPoller(
        repository=repo,
        account_provider=accounts,
        article_client=article_client,
        notifier=notifier,
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
        enabled: bool = True

    class CredentialRequest(BaseModel):
        id: str = "default"
        account_name: str = ""
        token: str = ""
        cookie: str = ""
        extra: dict[str, str] = {}
        expires_at: str | None = None

    app = FastAPI(title="wechat-rss-lite", version="0.2.0")

    def require_admin(authorization: str | None = Header(default=None)) -> None:
        if not settings.admin_token:
            return
        if authorization == f"Bearer {settings.admin_token}":
            return
        raise HTTPException(status_code=401, detail="Admin token required")

    @app.get("/", response_class=HTMLResponse)
    @app.get("/admin", response_class=HTMLResponse)
    async def admin() -> str:
        return ADMIN_HTML

    @app.get("/health")
    async def health() -> dict[str, Any]:
        credential = repo.get_credential()
        return {
            "status": "ok",
            "proxy_pool": proxies.status(),
            "credential": {
                "configured": credential is not None,
                "account_name": credential.account_name if credential else "",
                "expires_at": credential.expires_at.isoformat() if credential and credential.expires_at else None,
                "expired": credential.is_expired if credential else False,
            },
        }

    @app.post("/login/sessions", dependencies=[Depends(require_admin)])
    async def create_login_session() -> dict[str, Any]:
        return _login_session_to_dict(await auth.create_login_session())

    @app.get("/login/sessions/{session_id}", dependencies=[Depends(require_admin)])
    async def poll_login_session(session_id: str) -> dict[str, Any]:
        return _login_session_to_dict(await auth.poll_login_session(session_id))

    @app.post("/login/sessions/{session_id}/complete", dependencies=[Depends(require_admin)])
    async def complete_login_session(session_id: str) -> dict[str, Any]:
        return _credential_to_dict(await auth.complete_login_session(session_id))

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

    @app.post("/articles/parse")
    async def parse_article(request: ParseRequest) -> dict[str, Any]:
        try:
            article = await article_client.fetch_article(str(request.url))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _article_to_dict(article)

    @app.get("/accounts/search")
    async def search_accounts(query: str, limit: int = Query(default=10, ge=1, le=50)) -> list[dict[str, Any]]:
        return [account.__dict__ for account in await accounts.search_accounts(query, limit=limit)]

    @app.get("/accounts/{account_id}/articles")
    async def list_account_articles(
        account_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        keyword: str = "",
    ) -> list[dict[str, Any]]:
        summaries = await accounts.list_articles(account_id, offset=offset, limit=limit, keyword=keyword)
        return [summary.__dict__ for summary in summaries]

    @app.post("/subscriptions", dependencies=[Depends(require_admin)])
    async def subscribe(request: SubscriptionRequest) -> dict[str, Any]:
        subscription = Subscription(
            id=request.id,
            title=request.title,
            account_id=request.account_id or request.id,
            source_url=request.source_url,
            enabled=request.enabled,
        )
        repo.add_subscription(subscription)
        return _subscription_to_dict(subscription)

    @app.get("/subscriptions")
    async def list_subscriptions() -> list[dict[str, Any]]:
        return [_subscription_to_dict(subscription) for subscription in repo.list_subscriptions()]

    @app.delete("/subscriptions/{subscription_id}", dependencies=[Depends(require_admin)])
    async def delete_subscription(subscription_id: str) -> dict[str, bool]:
        repo.delete_subscription(subscription_id)
        return {"deleted": True}

    @app.post("/subscriptions/{subscription_id}/poll", dependencies=[Depends(require_admin)])
    async def poll_subscription(subscription_id: str, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        subscription = next((item for item in repo.list_subscriptions() if item.id == subscription_id), None)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return _poll_result_to_dict(await poller.poll_subscription(subscription, limit=limit))

    @app.post("/poll", dependencies=[Depends(require_admin)])
    async def poll_all(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return [_poll_result_to_dict(result) for result in await poller.poll_all(limit_per_subscription=limit)]

    @app.get("/poll/runs")
    async def poll_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return [_poll_result_to_dict(result) for result in repo.latest_poll_results(limit=limit)]

    @app.get("/feeds/{subscription_id}.xml")
    @app.get("/feeds/{subscription_id}.rss")
    async def feed(subscription_id: str, limit: int = Query(default=20, ge=1, le=100)) -> Response:
        subscription = next((item for item in repo.list_subscriptions() if item.id == subscription_id), None)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        xml = render_rss(
            title=subscription.title,
            link=f"{settings.site_url}/feeds/{subscription.id}.rss",
            description=f"RSS feed for {subscription.title}",
            articles=repo.recent_articles(subscription_id=subscription.id, limit=limit),
        )
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

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
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "images": [{"url": image.url, "alt": image.alt} for image in article.images],
    }


def _subscription_to_dict(subscription: Subscription) -> dict[str, Any]:
    return {
        "id": subscription.id,
        "title": subscription.title,
        "account_id": subscription.account_id,
        "source_url": subscription.source_url,
        "enabled": subscription.enabled,
        "created_at": subscription.created_at.isoformat(),
        "updated_at": subscription.updated_at.isoformat(),
    }


def _credential_to_dict(credential: Credential) -> dict[str, Any]:
    return {
        "id": credential.id,
        "account_name": credential.account_name,
        "configured": bool(credential.token or credential.cookie or credential.extra),
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
