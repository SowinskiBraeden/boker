#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'data' / 'boker-dev.sqlite3'}"
DEFAULT_SECRET_KEY = "change-this-before-deploying"

APP_VERSION = "2.5.35"


def load_local_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_local_env(BASE_DIR / ".env")


class Config:
    APP_VERSION: str = APP_VERSION
    SECRET_KEY: str = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_NAME: str = "myboker_org_session"
    WTF_CSRF_TIME_LIMIT: int = 3600
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:5000")
    MAIL_SERVER: str = os.getenv("MAIL_SERVER", "")
    MAIL_PORT: int = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS: bool = os.getenv("MAIL_USE_TLS", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    MAIL_USE_SSL: bool = os.getenv(
        "MAIL_USE_SSL",
        "true" if MAIL_PORT == 465 else "false",
    ).lower() in ("true", "1", "yes")
    MAIL_USERNAME: str | None = os.getenv("MAIL_USERNAME") or None
    MAIL_PASSWORD: str | None = os.getenv("MAIL_PASSWORD") or None
    MAIL_DEFAULT_SENDER: str = os.getenv("MAIL_DEFAULT_SENDER", "noreply@myboker.org")
    MAIL_TIMEOUT: float = float(os.getenv("MAIL_TIMEOUT", "5"))
    RATELIMIT_STORAGE_URI: str | None = os.getenv("RATELIMIT_STORAGE_URI") or None


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    PREFERRED_URL_SCHEME: str = "https"
