#!/usr/bin/env python3
from __future__ import annotations

import os

import click
from flask import Flask

from auth import current_user_id, is_logged_in
from config import Config, ProductionConfig
from db import database_extensions_available, db, init_database
from extensions import csrf, limiter, mail
from routes.account import account_bp
from routes.leagues import leagues_bp
from routes.public import public_bp
from storage import ensure_data_file
from utils import cents_to_dollars, safe_date_label


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    cfg = ProductionConfig if os.getenv("FLASK_ENV") == "production" else Config
    app.config.from_object(cfg)
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

    @app.cli.command("init-db")
    def init_db_command() -> None:
        if not database_extensions_available() or db is None:
            raise click.ClickException(
                "Database dependencies are not installed. Run pip install -r requirements.txt."
            )

        with app.app_context():
            db.create_all()

        click.echo("Initialized database tables.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
