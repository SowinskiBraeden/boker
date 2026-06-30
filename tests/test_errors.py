import re
import tempfile
import unittest
from pathlib import Path

from app import create_app
from boker.db import db


class ErrorPageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.app = create_app(
            {
                "TESTING": True,
                "PROPAGATE_EXCEPTIONS": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
                "WTF_CSRF_ENABLED": False,
            }
        )

        @self.app.get("/explode")
        def explode():
            raise RuntimeError("boom")

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        self.tmpdir.cleanup()

    def test_unexpected_errors_render_crash_page_with_incident_id(self):
        response = self.client.get("/explode")

        self.assertEqual(response.status_code, 500)
        self.assertIn(b"Something went wrong.", response.data)
        self.assertIn(b"Incident", response.data)
        self.assertNotIn(b"RuntimeError", response.data)
        self.assertRegex(response.get_data(as_text=True), re.compile(r"Incident [a-f0-9]{12}"))

    def test_csrf_errors_redirect_to_form_with_flash(self):
        csrf_app = create_app(
            {
                "TESTING": True,
                "PROPAGATE_EXCEPTIONS": False,
                "SQLALCHEMY_DATABASE_URI": self.app.config["SQLALCHEMY_DATABASE_URI"],
                "WTF_CSRF_ENABLED": True,
            }
        )
        client = csrf_app.test_client()

        response = client.post(
            "/account/login",
            data={"csrf_token": "stale-token", "email": "owner@example.com", "password": "password123"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/account/login")
        with client.session_transaction() as flask_session:
            flashes = flask_session.get("_flashes", [])
        self.assertIn(("error", "Your form expired. Please try again."), flashes)


if __name__ == "__main__":
    unittest.main()
