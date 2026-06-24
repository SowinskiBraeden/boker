#!/usr/bin/env python3
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

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


def db_ready() -> bool:
    return database_extensions_available() and db is not None


@account_bp.get("/")
@login_required
def home():
    return redirect(url_for("leagues.index"))


@account_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def register():
    if current_user_id():
        return redirect(url_for("leagues.index"))

    if not db_ready():
        flash("Account database is not available.", "error")
        return render_template("account_register.html", form={})

    form = {
        "email": request.form.get("email", "").strip(),
    }

    if request.method == "POST":
        from league_repositories import create_user, find_user_by_email

        email = normalize_email(form["email"])
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not email or "@" not in email:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        elif find_user_by_email(email):
            flash("An account already exists for that email.", "error")
        else:
            user = create_user(email, password)
            db.session.commit()
            log_user_in(user.id)
            flash("Account created.", "success")
            return redirect(url_for("leagues.new"))

    return render_template("account_register.html", form=form)


@account_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per minute")
def login():
    if current_user_id():
        return redirect(url_for("leagues.index"))

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
        else:
            log_user_in(user.id)
            next_url = request.args.get("next") or url_for("leagues.index")
            flash("Logged in.", "success")
            return redirect(next_url)

    return render_template("account_login.html", form=form)


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

    if not current_user_id():
        return redirect(url_for("account.login", next=url_for("account.accept_invite", token=token)))

    if not db_ready():
        flash("Account database is not available.", "error")
        return redirect(url_for("leagues.index"))

    from db_models import User
    from league_repositories import add_league_member, find_league_by_id, find_membership

    user = db.session.get(User, current_user_id())
    if user is None or user.email != data.get("email"):
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
