#!/usr/bin/env python3
from __future__ import annotations

import click
from flask import Flask, render_template

from auth import current_user_id, is_logged_in, normalize_email
from config import Config
from db import database_extensions_available, db, init_database
from extensions import csrf, limiter, mail
from routes.account import account_bp
from routes.leagues import leagues_bp
from routes.public import public_bp
from storage import ensure_data_file
from utils import cents_to_dollars, safe_date_label


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    ensure_data_file(app.config["DATA_PATH"])
    init_database(app)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    app.jinja_env.filters["money"] = cents_to_dollars
    app.jinja_env.filters["pretty_date"] = safe_date_label

    @app.context_processor
    def inject_globals() -> dict:
        return {
            "app_version": app.config["APP_VERSION"],
            "current_user_id": current_user_id(),
            "is_logged_in": is_logged_in(),
        }

    app.register_blueprint(public_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(leagues_bp)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("403.html"), 403

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

        from db_models import User

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

        from db_models import User

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

if __name__ == "__main__":
    app.run(debug=True)
