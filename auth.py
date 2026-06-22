#!/usr/bin/env python3
"""Authentication helpers.

Kept in its own module so both app.py (context processor) and routes/admin.py
(route guards) can import is_admin() without circular imports.
"""
from __future__ import annotations

from flask import session as flask_session


def is_admin() -> bool:
    return bool(flask_session.get("is_admin"))
