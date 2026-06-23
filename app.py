#!/usr/bin/env python3
from __future__ import annotations

from flask import Flask

from auth import is_admin
from config import Config
from routes.admin import admin_bp
from routes.public import public_bp
from storage import ensure_data_file
from utils import cents_to_dollars, safe_date_label


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    ensure_data_file(app.config["DATA_PATH"])

    app.jinja_env.filters["money"] = cents_to_dollars
    app.jinja_env.filters["pretty_date"] = safe_date_label

    @app.context_processor
    def inject_globals() -> dict:
        return {
            "app_version": app.config["APP_VERSION"],
            "is_admin": is_admin(),
        }

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
