from __future__ import annotations

import asyncio
import csv
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from ..config import Settings
from ..content_processor import (
    extract_images,
    normalize_content_image_proxy_urls,
    proxy_content_images,
    proxy_image_url,
)
from ..models import (
    Article,
    BackgroundJob,
    BlacklistEntry,
    Category,
    Credential,
    NotificationEvent,
    Subscription,
    VerificationChallenge,
)
from ..storage import SQLiteRepository
from ..webhook import WebhookNotifier


def public_feed_url(settings: Settings, path: str) -> str:
    """Build absolute feed URL; append ?token= when RSS_READ_TOKEN is set."""
    base = settings.site_url.rstrip("/")
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path.lstrip('/')}"
    if settings.rss_read_token:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={quote(settings.rss_read_token, safe='')}"
    return url


def article_to_dict(article: Article, *, image_proxy_base: str) -> dict[str, Any]:
    content_html = ""
    if article.content_html:
        content_html = normalize_content_image_proxy_urls(
            proxy_content_images(article.content_html, image_proxy_base)
        )
    images = article.images
    if not images and content_html:
        images = tuple(extract_images(content_html, article.url))
    return {
        "url": article.url,
        "title": article.title,
        "author": article.author,
        "account_name": article.account_name,
        "summary": article.summary,
        "content_html": content_html,
        "text": article.text,
        "content_type": article.content_type,
        "unavailable_reason": article.unavailable_reason,
        "status": article.status,
        "source": article.source,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "images": [
            {"url": proxy_image_url(image.url, image_proxy_base), "alt": image.alt}
            for image in images
        ],
    }


def account_to_dict(account: Any) -> dict[str, Any]:
    avatar_url = account.avatar_url
    return {
        "id": account.id,
        "name": account.name,
        "alias": account.alias,
        "avatar_url": f"/image?url={quote(avatar_url, safe='')}" if avatar_url else "",
        "raw_avatar_url": avatar_url,
        "description": account.description,
    }


def subscription_to_dict(
    subscription: Subscription,
    *,
    settings: Settings | None = None,
    article_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    if settings:
        feed_url = public_feed_url(settings, f"/feeds/{subscription.id}.rss")
        history_feed_url = public_feed_url(settings, f"/feeds/{subscription.id}/history.rss")
    else:
        feed_url = f"/feeds/{subscription.id}.rss"
        history_feed_url = f"/feeds/{subscription.id}/history.rss"
    return {
        "id": subscription.id,
        "title": subscription.title,
        "account_id": subscription.account_id,
        "source_url": subscription.source_url,
        "avatar_url": subscription.avatar_url,
        "description": subscription.description,
        "category_id": subscription.category_id,
        "feed_url": feed_url,
        "history_feed_url": history_feed_url,
        "enabled": subscription.enabled,
        "created_at": subscription.created_at.isoformat(),
        "updated_at": subscription.updated_at.isoformat(),
        "article_total": (article_stats or {}).get("article_total", 0),
        "article_fetched": (article_stats or {}).get("article_fetched", 0),
        "article_pending": (article_stats or {}).get("article_pending", 0),
        "article_failed": (article_stats or {}).get("article_failed", 0),
        "article_remaining": (article_stats or {}).get("article_remaining", 0),
    }


def category_to_dict(category: Category, *, repo: SQLiteRepository) -> dict[str, Any]:
    return {
        "id": category.id,
        "name": category.name,
        "description": category.description,
        "color": category.color,
        "sort_order": category.sort_order,
        "subscription_count": sum(1 for item in repo.list_subscriptions() if item.category_id == category.id),
        "created_at": category.created_at.isoformat(),
    }


def credential_to_dict(credential: Credential) -> dict[str, Any]:
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


def login_session_to_dict(session: Any) -> dict[str, Any]:
    return {
        "id": session.id,
        "qrcode_url": session.qrcode_url,
        "status": getattr(session.status, "value", session.status),
        "message": session.message,
        "confirm_url": getattr(session, "confirm_url", ""),
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
    }


def poll_result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "subscription_id": result.subscription_id,
        "fetched": result.fetched,
        "stored": result.stored,
        "failed": result.failed,
        "message": result.message,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
    }


def background_job_to_dict(job: BackgroundJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "target": job.target,
        "total": job.total,
        "processed": job.processed,
        "succeeded": job.succeeded,
        "failed": job.failed,
        "message": job.message,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def verification_to_dict(challenge: VerificationChallenge) -> dict[str, Any]:
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


def blacklist_to_dict(entry: BlacklistEntry) -> dict[str, Any]:
    return {
        "account_id": entry.account_id,
        "reason": entry.reason,
        "created_at": entry.created_at.isoformat(),
    }


def subscriptions_csv(subscriptions: list[Subscription], *, settings: Settings) -> Any:
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
                public_feed_url(settings, f"/feeds/{subscription.id}.rss"),
                public_feed_url(settings, f"/feeds/{subscription.id}/history.rss"),
                subscription.category_id or "",
                "yes" if subscription.enabled else "no",
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="wechat_rss_subscriptions.csv"'},
    )


def subscriptions_opml(subscriptions: list[Subscription], *, settings: Settings) -> Any:
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
                "xmlUrl": public_feed_url(settings, f"/feeds/{subscription.id}.rss"),
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


async def polling_loop(poller: RssPoller, interval_seconds: int) -> None:
    interval = max(interval_seconds, 60)
    while True:
        await asyncio.sleep(interval)
        try:
            await poller.poll_all()
        except Exception:
            continue


async def credential_reminder_loop(repo: SQLiteRepository, notifier: WebhookNotifier) -> None:
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
