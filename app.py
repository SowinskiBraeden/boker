#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from auth import is_admin
from config import Config
from routes.admin import admin_bp
from routes.public import public_bp
from storage import ensure_data_file
from utils import cents_to_dollars, safe_date_label


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


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    ensure_data_file(app.config["DATA_PATH"])

    app.jinja_env.filters["money"] = cents_to_dollars
    app.jinja_env.filters["pretty_date"] = safe_date_label

    @app.context_processor
    def inject_globals() -> dict:
        return {"is_admin": is_admin()}

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    return app


_env_path = Path(__file__).resolve().parent / ".env"
load_local_env(_env_path)

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
