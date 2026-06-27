#!/usr/bin/env python3
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, session as flask_session, url_for

from auth import (
    current_user_id,
    generate_invite_token,
    generate_reset_token,
    hash_password,
    log_user_in,
    log_user_out,
    login_required,
    normalize_email,
    verify_invite_token,
    verify_password,
    verify_reset_token,
)
from db import database_extensions_available, db
from extensions import limiter

account_bp = Blueprint("account", __name__, url_prefix="/account")
EMAIL_VERIFICATION_TTL = timedelta(minutes=15)


def db_ready() -> bool:
    return database_extensions_available() and db is not None


def safe_next_url(default: str) -> str:
    next_url = request.args.get("next", "").strip()
    if not next_url:
        return default

    parsed = urlsplit(next_url)
    if parsed.scheme or parsed.netloc:
        return default
    if not next_url.startswith("/"):
        return default
    return next_url


def _verification_next(default: str) -> str:
    next_url = flask_session.get("pending_verification_next")
    if isinstance(next_url, str) and next_url.startswith("/") and not urlsplit(next_url).netloc:
        return next_url
    return default


def _verification_sent_at_valid(sent_at) -> bool:
    if sent_at is None:
        return False
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - sent_at <= EMAIL_VERIFICATION_TTL


def _new_verification_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def _issue_verification_code(user) -> str:
    from db_models import utc_now

    code = _new_verification_code()
    user.email_verification_code_hash = hash_password(code)
    user.email_verification_sent_at = utc_now()
    return code


def _send_verification_code(user) -> None:
    from emails import send_email_verification_code

    code = _issue_verification_code(user)
    db.session.commit()
    send_email_verification_code(user.email, code)


def _start_email_verification(user, next_url: str) -> str:
    flask_session["pending_verification_user_id"] = user.id
    flask_session["pending_verification_next"] = next_url
    try:
        _send_verification_code(user)
        flash("Check your email for a verification code.", "success")
    except Exception:
        flash("Account created, but we could not send a verification code. Try resending it.", "error")
    return url_for("account.verify_email")


@account_bp.get("/")
@login_required
def home():
    return redirect(url_for("leagues.index"))


@account_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def register():
    if current_user_id():
        return redirect(safe_next_url(url_for("leagues.index")))

    if not db_ready():
        flash("Account database is not available.", "error")
        return render_template("account_register.html", form={})

    form = {
        "email": (request.form.get("email") or request.args.get("email") or "").strip(),
    }

    if request.method == "POST":
        from league_repositories import create_user, find_user_by_email

        email = normalize_email(form["email"])
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        existing_user = find_user_by_email(email)

        if not email or "@" not in email:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        elif existing_user and existing_user.disabled_at is None:
            flash("An account already exists for that email.", "error")
        else:
            if existing_user:
                user = existing_user
                user.password_hash = hash_password(password)
                user.disabled_at = None
                user.email_verified_at = None
                user.email_verification_code_hash = None
                user.email_verification_sent_at = None
            else:
                user = create_user(email, password)
            db.session.flush()
            return redirect(_start_email_verification(user, safe_next_url(url_for("leagues.new"))))

    return render_template("account_register.html", form=form)


@account_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per minute")
def login():
    if current_user_id():
        return redirect(safe_next_url(url_for("leagues.index")))

    if not db_ready():
        flash("Account database is not available.", "error")
        return render_template("account_login.html", form={})

    form = {
        "email": request.form.get("email", "").strip(),
    }

    if request.method == "POST":
        from league_repositories import find_user_by_email

        user = find_user_by_email(form["email"])
        password = request.form.get("password", "")

        if user is None or not verify_password(user.password_hash, password):
            flash("Invalid email or password.", "error")
        elif user.disabled_at is not None:
            flash("That account is disabled.", "error")
        elif user.email_verified_at is None:
            flask_session["pending_verification_user_id"] = user.id
            flask_session["pending_verification_next"] = safe_next_url(url_for("leagues.index"))
            try:
                _send_verification_code(user)
                flash("Verify your email to continue. We sent you a new code.", "success")
            except Exception:
                flash("Verify your email to continue. We could not send a new code.", "error")
            return redirect(url_for("account.verify_email"))
        else:
            log_user_in(user.id)
            next_url = safe_next_url(url_for("leagues.index"))
            flash("Logged in.", "success")
            return redirect(next_url)

    return render_template("account_login.html", form=form)


@account_bp.route("/verify-email", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def verify_email():
    if current_user_id():
        return redirect(safe_next_url(url_for("leagues.index")))

    if not db_ready():
        flash("Account database is not available.", "error")
        return redirect(url_for("account.login"))

    from db_models import User, utc_now

    user_id = flask_session.get("pending_verification_user_id")
    user = db.session.get(User, user_id) if user_id else None
    if user is None or user.disabled_at is not None:
        flask_session.pop("pending_verification_user_id", None)
        flask_session.pop("pending_verification_next", None)
        flash("Start again to verify your email.", "error")
        return redirect(url_for("account.register"))

    if user.email_verified_at is not None:
        log_user_in(user.id)
        next_url = _verification_next(url_for("leagues.index"))
        flask_session.pop("pending_verification_user_id", None)
        flask_session.pop("pending_verification_next", None)
        return redirect(next_url)

    if request.method == "POST":
        code = "".join(ch for ch in request.form.get("code", "") if ch.isdigit())
        if len(code) != 6:
            flash("Enter the six-digit verification code.", "error")
        elif not _verification_sent_at_valid(user.email_verification_sent_at):
            flash("That code has expired. Request a new one.", "error")
        elif not user.email_verification_code_hash or not verify_password(user.email_verification_code_hash, code):
            flash("That verification code is not correct.", "error")
        else:
            user.email_verified_at = utc_now()
            user.email_verification_code_hash = None
            user.email_verification_sent_at = None
            db.session.commit()
            log_user_in(user.id)
            next_url = _verification_next(url_for("leagues.index"))
            flask_session.pop("pending_verification_user_id", None)
            flask_session.pop("pending_verification_next", None)
            flash("Email verified.", "success")
            return redirect(next_url)

    return render_template("account_verify_email.html", email=user.email)


@account_bp.post("/verify-email/resend")
@limiter.limit("3 per minute")
def resend_verification_code():
    if current_user_id():
        return redirect(url_for("leagues.index"))

    if not db_ready():
        flash("Account database is not available.", "error")
        return redirect(url_for("account.login"))

    from db_models import User

    user_id = flask_session.get("pending_verification_user_id")
    user = db.session.get(User, user_id) if user_id else None
    if user is None or user.disabled_at is not None:
        flash("Start again to verify your email.", "error")
        return redirect(url_for("account.register"))

    try:
        _send_verification_code(user)
        flash("A new verification code has been sent.", "success")
    except Exception:
        flash("We could not send a new code. Check your mail configuration.", "error")
    return redirect(url_for("account.verify_email"))


@account_bp.post("/logout")
def logout():
    log_user_out()
    flash("Logged out.", "success")
    return redirect(url_for("public.home"))


@account_bp.get("/settings")
@login_required
def settings():
    if not db_ready():
        flash("Account database is not available.", "error")
        return redirect(url_for("leagues.index"))

    from db_models import User

    user = db.session.get(User, current_user_id())
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("public.home"))

    return render_template("account_settings.html", user=user)


@account_bp.post("/settings/email")
@login_required
def update_email():
    if not db_ready():
        flash("Account database is not available.", "error")
        return redirect(url_for("account.settings"))

    from db_models import User

    user = db.session.get(User, current_user_id())
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("account.settings"))

    new_email = normalize_email(request.form.get("email", ""))
    current_password = request.form.get("current_password", "")

    if not new_email or "@" not in new_email:
        flash("Enter a valid email address.", "error")
    elif not verify_password(user.password_hash, current_password):
        flash("Current password is incorrect.", "error")
    else:
        from league_repositories import find_user_by_email

        existing = find_user_by_email(new_email)
        if existing and existing.id != user.id:
            flash("That email is already in use.", "error")
        else:
            user.email = new_email
            db.session.commit()
            flash("Email updated.", "success")

    return redirect(url_for("account.settings"))


@account_bp.post("/settings/password")
@login_required
def update_password():
    if not db_ready():
        flash("Account database is not available.", "error")
        return redirect(url_for("account.settings"))

    from db_models import User

    user = db.session.get(User, current_user_id())
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("account.settings"))

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not verify_password(user.password_hash, current_password):
        flash("Current password is incorrect.", "error")
    elif len(new_password) < 8:
        flash("New password must be at least 8 characters.", "error")
    elif new_password != confirm_password:
        flash("Passwords do not match.", "error")
    else:
        user.password_hash = hash_password(new_password)
        db.session.commit()
        flash("Password changed.", "success")

    return redirect(url_for("account.settings"))


@account_bp.post("/delete")
@login_required
def delete_account():
    if not db_ready():
        flash("Account database is not available.", "error")
        return redirect(url_for("account.settings"))

    from db_models import League, User, utc_now

    user = db.session.get(User, current_user_id())
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("account.settings"))

    confirm = request.form.get("confirm", "").strip()
    current_password = request.form.get("current_password", "")

    if confirm != "DELETE":
        flash("Confirmation text did not match.", "error")
        return redirect(url_for("account.settings"))

    if not verify_password(user.password_hash, current_password):
        flash("Password is incorrect.", "error")
        return redirect(url_for("account.settings"))

    owned_leagues = League.query.filter_by(created_by_user_id=user.id, archived_at=None).all()
    for league in owned_leagues:
        league.archived_at = utc_now()

    user.disabled_at = utc_now()
    db.session.commit()
    log_user_out()
    flash("Your account has been deleted.", "success")
    return redirect(url_for("public.home"))


@account_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def forgot_password():
    if current_user_id():
        return redirect(url_for("leagues.index"))

    if request.method == "POST":
        if not db_ready():
            flash("Account database is not available.", "error")
            return redirect(url_for("account.forgot_password"))

        from emails import send_password_reset
        from flask import current_app
        from league_repositories import find_user_by_email

        email = normalize_email(request.form.get("email", ""))
        user = find_user_by_email(email)

        if user and user.disabled_at is None:
            token = generate_reset_token(user.id)
            base_url = current_app.config.get("APP_BASE_URL", "").rstrip("/")
            reset_url = f"{base_url}{url_for('account.reset_password', token=token)}"
            try:
                send_password_reset(email, reset_url)
            except Exception:
                pass

        flash("If that email is registered, a reset link has been sent.", "success")
        return redirect(url_for("account.login"))

    return render_template("forgot_password.html")


@account_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user_id():
        return redirect(url_for("leagues.index"))

    user_id = verify_reset_token(token)
    if user_id is None:
        flash("That reset link is invalid or has expired.", "error")
        return redirect(url_for("account.forgot_password"))

    if not db_ready():
        flash("Account database is not available.", "error")
        return redirect(url_for("account.login"))

    from db_models import User

    user = db.session.get(User, user_id)
    if user is None or user.disabled_at is not None:
        flash("That reset link is invalid or has expired.", "error")
        return redirect(url_for("account.forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif new_password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            user.password_hash = hash_password(new_password)
            db.session.commit()
            flash("Password reset. You can now log in.", "success")
            return redirect(url_for("account.login"))

    return render_template("reset_password.html", token=token)


@account_bp.get("/accept-invite/<token>")
def accept_invite(token):
    data = verify_invite_token(token)
    if data is None:
        flash("That invitation link is invalid or has expired.", "error")
        return redirect(url_for("public.home"))

    if not db_ready():
        flash("Account database is not available.", "error")
        return redirect(url_for("leagues.index"))

    from db_models import User
    from league_repositories import add_league_member, find_league_by_id, find_membership, find_user_by_email

    invite_email = normalize_email(data.get("email", ""))
    invite_next = url_for("account.accept_invite", token=token)
    if not current_user_id():
        if find_user_by_email(invite_email):
            flash("Sign in to accept your invitation.", "info")
            return redirect(url_for("account.login", next=invite_next))

        flash("Create an account to accept your invitation.", "info")
        return redirect(url_for("account.register", next=invite_next, email=invite_email))

    user = db.session.get(User, current_user_id())
    if user is None or user.email != invite_email:
        flash("This invitation was sent to a different email address.", "error")
        return redirect(url_for("leagues.index"))

    league = find_league_by_id(data["league_id"])
    if league is None:
        flash("That league no longer exists.", "error")
        return redirect(url_for("leagues.index"))

    existing = find_membership(league.id, user.id)
    if existing:
        flash(f"You are already a member of {league.name}.", "info")
        return redirect(url_for("leagues.dashboard", league_ref=league.url_ref))

    add_league_member(league.id, user.id, data["role"], data.get("invited_by", ""))
    db.session.commit()
    flash(f"Welcome to {league.name}! You joined as {data['role']}.", "success")
    return redirect(url_for("leagues.dashboard", league_ref=league.url_ref))
