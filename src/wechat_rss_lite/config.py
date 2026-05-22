from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("wechat-rss-lite.db")
    database_url: str = ""
    database_schema: str = "wechat_rss_lite"
    site_url: str = "http://localhost:8080"
    poll_interval_seconds: int = 3600
    request_timeout_seconds: float = 15.0
    request_retries: int = 2
    article_transport: str = "auto"
    rate_limit_per_minute: int = 6
    article_interval_seconds: float = 10.0
    proxy_urls: tuple[str, ...] = ()
    webhook_url: str = ""
    admin_token: str = ""
    rss_read_token: str = ""
    login_provider: str = "wechat"
    background_polling: bool = False
    credential_reminders: bool = False
    verification_blacklist_threshold: int = 3
    refresh_batch_limit: int = 50
    tls_verify: bool = True
    allowed_image_hosts: tuple[str, ...] = (
        "mmbiz.qpic.cn",
        "mmbiz.qlogo.cn",
        "mp.weixin.qq.com",
        "wx.qlogo.cn",
        "res.wx.qq.com",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        return cls(
            db_path=Path(os.getenv("WECHAT_RSS_DB_PATH", "wechat-rss-lite.db")),
            database_url=(
                os.getenv("WECHAT_RSS_DATABASE_URL", "").strip()
                or os.getenv("DATABASE_URL", "").strip()
            ),
            database_schema=os.getenv("WECHAT_RSS_DATABASE_SCHEMA", "wechat_rss_lite").strip()
            or "wechat_rss_lite",
            site_url=os.getenv("SITE_URL", "http://localhost:8080").rstrip("/"),
            poll_interval_seconds=_int("RSS_POLL_INTERVAL", 3600),
            request_timeout_seconds=_float("REQUEST_TIMEOUT_SECONDS", 15.0),
            request_retries=_int("REQUEST_RETRIES", 2),
            article_transport=os.getenv("ARTICLE_TRANSPORT", "auto").strip().lower() or "auto",
            rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 6),
            article_interval_seconds=_float("ARTICLE_INTERVAL_SECONDS", 10.0),
            proxy_urls=_csv("PROXY_URLS"),
            webhook_url=os.getenv("WEBHOOK_URL", ""),
            admin_token=os.getenv("ADMIN_API_TOKEN", ""),
            rss_read_token=os.getenv("RSS_READ_TOKEN", ""),
            login_provider=os.getenv("LOGIN_PROVIDER", "wechat"),
            background_polling=_bool("BACKGROUND_POLLING", False),
            credential_reminders=_bool("CREDENTIAL_REMINDERS", False),
            verification_blacklist_threshold=_int("VERIFICATION_BLACKLIST_THRESHOLD", 3),
            refresh_batch_limit=_int("REFRESH_BATCH_LIMIT", 50),
            tls_verify=_bool("CURL_TLS_VERIFY", True),
            allowed_image_hosts=_csv("ALLOWED_IMAGE_HOSTS")
            or (
                "mmbiz.qpic.cn",
                "mmbiz.qlogo.cn",
                "mp.weixin.qq.com",
                "wx.qlogo.cn",
                "res.wx.qq.com",
            ),
        )


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env", override=False)


def _csv(name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, "").split(",") if value.strip())


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
