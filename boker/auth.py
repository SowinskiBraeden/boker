#!/usr/bin/env python3
from __future__ import annotations

from functools import wraps

from flask import abort, current_app, flash, redirect, request, session as flask_session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_reset_token(user_id: str) -> str:
    return _serializer().dumps(user_id, salt="password-reset")


def verify_reset_token(token: str, max_age: int = 3600) -> str | None:
    try:
        return _serializer().loads(token, salt="password-reset", max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None


def generate_invite_token(league_id: str, email: str, role: str, invited_by_user_id: str) -> str:
    return _serializer().dumps(
        {"league_id": league_id, "email": email, "role": role, "invited_by": invited_by_user_id},
        salt="league-invite",
    )


def verify_invite_token(token: str, max_age: int = 604800) -> dict | None:
    try:
        data = _serializer().loads(token, salt="league-invite", max_age=max_age)
        return data if isinstance(data, dict) else None
    except (SignatureExpired, BadSignature):
        return None


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def log_user_in(user_id: str) -> None:
    flask_session["user_id"] = user_id


def log_user_out() -> None:
    flask_session.pop("user_id", None)


def current_user_id() -> str | None:
    user_id = flask_session.get("user_id")
    return str(user_id) if user_id else None


def is_logged_in() -> bool:
    return current_user_id() is not None


def is_site_admin() -> bool:
    user_id = current_user_id()
    if not user_id:
        return False

    from boker.db import database_extensions_available

    if not database_extensions_available():
        return False

    from boker.db_models import User

    user = User.query.filter_by(id=user_id, disabled_at=None).one_or_none()
    return bool(user and user.is_site_admin)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not is_logged_in():
            flash("Login required.", "error")
            return redirect(url_for("account.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped_view


def site_admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not is_logged_in():
            flash("Login required.", "error")
            return redirect(url_for("account.login", next=request.full_path))
        if not is_site_admin():
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view
