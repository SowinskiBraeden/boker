#!/usr/bin/env python3
from __future__ import annotations

import click
import os
from uuid import uuid4

from flask import Flask, render_template, request
from werkzeug.exceptions import HTTPException

from boker.auth import current_user_id, is_logged_in, is_site_admin, normalize_email
from boker.config import DEFAULT_DATABASE_URL, DEFAULT_SECRET_KEY, Config, ProductionConfig
from boker.db import database_extensions_available, db, init_database
from boker.extensions import csrf, limiter, mail
from boker.routes.account import account_bp
from boker.routes.internal import internal_bp
from boker.routes.leagues import leagues_bp
from boker.routes.public import public_bp
from boker.utils import cents_to_dollars, safe_date_label


def _config_for_environment():
    app_env = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "")).lower()
    if app_env in {"prod", "production"}:
        return ProductionConfig
    return Config


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(_config_for_environment())
    if config_overrides:
        app.config.update(config_overrides)

    if app.config["SESSION_COOKIE_SECURE"] and app.config["SECRET_KEY"] == DEFAULT_SECRET_KEY:
        raise RuntimeError("Set SECRET_KEY before running in production.")
    if app.config["SESSION_COOKIE_SECURE"]:
        database_url = app.config["SQLALCHEMY_DATABASE_URI"]
        if database_url == DEFAULT_DATABASE_URL or database_url.startswith("sqlite:"):
            raise RuntimeError("Set DATABASE_URL to a production PostgreSQL database before running in production.")

    init_database(app)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    app.jinja_env.filters["money"] = cents_to_dollars
    app.jinja_env.filters["pretty_date"] = safe_date_label

    @app.context_processor
    def inject_globals() -> dict:
        base_url = app.config.get("APP_BASE_URL", "https://myboker.org").rstrip("/")
        return {
            "app_version": app.config["APP_VERSION"],
            "current_user_id": current_user_id(),
            "is_logged_in": is_logged_in(),
            "current_user_is_site_admin": is_site_admin(),
            "seo_site_url": base_url,
            "seo_canonical_url": f"{base_url}{request.path}",
            "seo_default_description": (
                "myboker.org is a free poker tracker and poker ledger for home games, "
                "private leagues, player stats, profit and loss tracking, buy-ins, "
                "cashouts, settlements, and bookkeeping records."
            ),
            "seo_default_keywords": (
                "myboker, my boker, free poker tracker, poker ledger, poker stats, "
                "poker profit tracker, poker loss tracker, home poker tracker, "
                "poker bankroll tracker, poker bookkeeping, poker league tracker"
            ),
        }

    app.register_blueprint(public_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(internal_bp)
    app.register_blueprint(leagues_bp)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("403.html"), 403

    @app.errorhandler(Exception)
    def unexpected_error(error):
        if isinstance(error, HTTPException):
            return error

        crash_id = uuid4().hex[:12]
        app.logger.exception(
            "Unhandled exception [%s] during %s %s",
            crash_id,
            request.method,
            request.path,
        )
        return render_template("500.html", crash_id=crash_id), 500

    @app.cli.command("init-db")
    def init_db_command() -> None:
        if not database_extensions_available() or db is None:
            raise click.ClickException(
                "Database dependencies are not installed. Run pip install -r requirements.txt."
            )

        with app.app_context():
            db.create_all()

        click.echo("Initialized database tables.")

    @app.cli.command("grant-site-admin")
    @click.argument("email")
    def grant_site_admin_command(email: str) -> None:
        if not database_extensions_available() or db is None:
            raise click.ClickException(
                "Database dependencies are not installed. Run pip install -r requirements.txt."
            )

        from boker.db_models import User

        normalized_email = normalize_email(email)
        with app.app_context():
            user = User.query.filter_by(email=normalized_email, disabled_at=None).one_or_none()
            if user is None:
                raise click.ClickException(f"No active user found for {normalized_email}.")
            user.is_site_admin = True
            db.session.commit()

        click.echo(f"Granted site admin access to {normalized_email}.")

    @app.cli.command("revoke-site-admin")
    @click.argument("email")
    def revoke_site_admin_command(email: str) -> None:
        if not database_extensions_available() or db is None:
            raise click.ClickException(
                "Database dependencies are not installed. Run pip install -r requirements.txt."
            )

        from boker.db_models import User

        normalized_email = normalize_email(email)
        with app.app_context():
            user = User.query.filter_by(email=normalized_email).one_or_none()
            if user is None:
                raise click.ClickException(f"No user found for {normalized_email}.")
            user.is_site_admin = False
            db.session.commit()

        click.echo(f"Revoked site admin access from {normalized_email}.")

    return app


app = create_app()
