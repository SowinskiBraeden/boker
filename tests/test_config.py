import os
import unittest
from unittest.mock import patch

from app import create_app
from boker.config import DEFAULT_DATABASE_URL


class ProductionConfigTests(unittest.TestCase):
    def test_production_refuses_default_sqlite_database(self):
        with patch.dict(
            os.environ,
            {"APP_ENV": "production"},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                create_app(
                    {
                        "SECRET_KEY": "test-production-secret",
                        "SQLALCHEMY_DATABASE_URI": DEFAULT_DATABASE_URL,
                    }
                )

    def test_production_accepts_postgresql_database_url(self):
        with patch.dict(
            os.environ,
            {"APP_ENV": "production"},
            clear=False,
        ):
            app = create_app(
                {
                    "SECRET_KEY": "test-production-secret",
                    "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://user:password@example.com/dbname",
                }
            )

        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])
        self.assertEqual(app.config["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertTrue(app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://"))


if __name__ == "__main__":
    unittest.main()
