import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask_mail import Message

from boker import create_app
from boker.db import db
from boker.emails import MailNotConfiguredError, send_email_verification
from boker.repositories.leagues import create_user


class EmailDeliveryTests(unittest.TestCase):
    def test_blank_mail_server_fails_before_smtp_send(self):
        app = create_app({"MAIL_SERVER": "", "TESTING": True})

        with app.app_context():
            with patch("boker.emails.mail.send") as send:
                with self.assertRaises(MailNotConfiguredError):
                    send_email_verification("user@example.com", "http://localhost/verify")

        send.assert_not_called()

    def test_smtp_send_uses_configured_socket_timeout(self):
        app = create_app({"MAIL_SERVER": "smtp.example.com", "MAIL_SEND_TIMEOUT": 1.5, "TESTING": True})
        msg = Message(
            subject="Test",
            recipients=["user@example.com"],
            body="body",
            sender="noreply@example.com",
        )
        observed_timeout = None

        def capture_timeout(_msg):
            nonlocal observed_timeout
            observed_timeout = socket.getdefaulttimeout()

        with app.app_context():
            previous_timeout = socket.getdefaulttimeout()
            with patch("boker.emails.mail.send", side_effect=capture_timeout):
                from boker.emails import _send

                _send(msg)

        self.assertEqual(observed_timeout, 1.5)
        self.assertEqual(socket.getdefaulttimeout(), previous_timeout)

    def test_resend_verification_returns_when_mail_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite3"
            app = create_app(
                {
                    "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
                    "MAIL_SERVER": "",
                    "TESTING": True,
                    "WTF_CSRF_ENABLED": False,
                }
            )

            with app.app_context():
                db.create_all()
                user = create_user("user@example.com", "password123")
                db.session.commit()
                user_id = user.id

            with app.test_client() as client:
                with client.session_transaction() as flask_session:
                    flask_session["user_id"] = user_id

                response = client.post("/account/resend-verification")

            with app.app_context():
                db.session.remove()
                db.drop_all()
                db.engine.dispose()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/account/settings")


if __name__ == "__main__":
    unittest.main()
