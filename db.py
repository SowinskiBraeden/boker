#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

try:
    from flask_migrate import Migrate
    from flask_sqlalchemy import SQLAlchemy
except ModuleNotFoundError:  # pragma: no cover - exercised only before deps install.
    Migrate = None
    SQLAlchemy = None


db = SQLAlchemy() if SQLAlchemy is not None else None
migrate = Migrate() if Migrate is not None else None


def database_extensions_available() -> bool:
    return db is not None and migrate is not None


def init_database(app: Any) -> bool:
    if not database_extensions_available():
        app.config["DATABASE_EXTENSIONS_AVAILABLE"] = False
        return False

    import db_models  # noqa: F401 - registers SQLAlchemy models with metadata.

    db.init_app(app)
    migrate.init_app(app, db)
    app.config["DATABASE_EXTENSIONS_AVAILABLE"] = True
    return True
