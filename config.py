#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "entries.csv"

ELIGIBLE_MIN_SESSIONS = 3


class Config:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-before-deploying")
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "change-me")
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_NAME: str = "poker_portal_session"
    DATA_PATH: Path = DATA_PATH
