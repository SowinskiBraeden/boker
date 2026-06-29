#!/usr/bin/env python3
from __future__ import annotations

from boker.app import app, create_app

__all__ = ["app", "create_app"]


if __name__ == "__main__":
    app.run(debug=True)
