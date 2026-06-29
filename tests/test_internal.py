import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import create_app
from auth import hash_password
from db import db


class InternalAdminAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.client = self.app.test_client()

        with self.app.app_context():
            from db_models import League, LeagueMembership, User

            db.create_all()
            self.user = User(
                email="viewer@example.com",
                password_hash=hash_password("password123"),
            )
            self.manager = User(
                email="manager@example.com",
                password_hash=hash_password("password123"),
            )
            self.admin = User(
                email="admin@example.com",
                password_hash=hash_password("password123"),
                is_site_admin=True,
            )
            db.session.add_all([self.user, self.manager, self.admin])
            db.session.flush()
            self.league = League(
                name="Friday Poker",
                slug="friday-poker",
                public_key="abc123",
                created_by_user_id=self.admin.id,
                visibility="public",
            )
            db.session.add(self.league)
            db.session.flush()
            db.session.add_all(
                [
                    LeagueMembership(league_id=self.league.id, user_id=self.admin.id, role="owner"),
                    LeagueMembership(league_id=self.league.id, user_id=self.manager.id, role="manager"),
                ]
            )
            db.session.commit()
            self.user_id = self.user.id
            self.manager_id = self.manager.id
            self.admin_id = self.admin.id
            self.league_id = self.league.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        self.tmpdir.cleanup()

    def login_as(self, user_id: str, **extra_session):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            for key, value in extra_session.items():
                session[key] = value

    def test_internal_dashboard_requires_login(self):
        response = self.client.get("/internal/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/login", response.headers["Location"])

    def test_internal_dashboard_rejects_regular_users(self):
        self.login_as(self.user_id)

        response = self.client.get("/internal/")

        self.assertEqual(response.status_code, 403)

    def test_internal_dashboard_ignores_client_side_admin_spoof(self):
        self.login_as(self.user_id, is_site_admin=True)

        response = self.client.get("/internal/")

        self.assertEqual(response.status_code, 403)

    def test_internal_dashboard_allows_site_admins(self):
        self.login_as(self.admin_id)

        response = self.client.get("/internal/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Overview", response.data)
        self.assertIn(b"admin@example.com", response.data)
        self.assertIn(b"Active users", response.data)
        self.assertIn(b"Activity breakdown", response.data)
        self.assertIn(b"Ledger events", response.data)
        self.assertIn(b"Totals at a glance", response.data)

    def test_admin_can_search_users(self):
        self.login_as(self.admin_id)

        response = self.client.get("/internal/users?q=viewer")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"viewer@example.com", response.data)
        self.assertNotIn(b"manager@example.com", response.data)

    def test_admin_users_page_is_paginated(self):
        with self.app.app_context():
            from db_models import User

            users = [
                User(email=f"bulk{i:02d}@example.com", password_hash=hash_password("password123"))
                for i in range(55)
            ]
            db.session.add_all(users)
            db.session.commit()
        self.login_as(self.admin_id)

        response = self.client.get("/internal/users?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Page 2 of 2", response.data)
        self.assertIn(b"Previous", response.data)

    def test_admin_leagues_page_is_paginated(self):
        with self.app.app_context():
            from db_models import League

            leagues = [
                League(
                    name=f"Bulk League {i:02d}",
                    slug=f"bulk-league-{i:02d}",
                    public_key=f"bk{i:010d}"[:12],
                    created_by_user_id=self.admin_id,
                    visibility="private",
                )
                for i in range(55)
            ]
            db.session.add_all(leagues)
            db.session.commit()
        self.login_as(self.admin_id)

        response = self.client.get("/internal/leagues?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Page 2 of 2", response.data)
        self.assertIn(b"Previous", response.data)

    def test_session_growth_uses_session_date_not_created_at(self):
        with self.app.app_context():
            from db_models import PokerSession
            from routes.internal import _growth_data

            now = datetime.now(timezone.utc)
            old_session = PokerSession(
                league_id=self.league_id,
                session_date=(now - timedelta(weeks=5)).date(),
                sequence_on_date=1,
                status="closed",
                created_at=now,
            )
            current_session = PokerSession(
                league_id=self.league_id,
                session_date=(now - timedelta(days=2)).date(),
                sequence_on_date=1,
                status="closed",
                created_at=now,
            )
            db.session.add_all([old_session, current_session])
            db.session.commit()

            growth = _growth_data()

            self.assertEqual(sum(growth["session_counts"]), 2)
            self.assertLess(growth["session_counts"][-1], 2)

    def test_regular_user_cannot_update_user_email(self):
        self.login_as(self.user_id)

        response = self.client.post(
            f"/internal/users/{self.user_id}/email",
            data={"email": "changed@example.com"},
        )

        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            from db_models import User

            user = db.session.get(User, self.user_id)
            self.assertEqual(user.email, "viewer@example.com")

    def test_admin_can_update_user_email(self):
        self.login_as(self.admin_id)

        response = self.client.post(
            f"/internal/users/{self.user_id}/email",
            data={"email": "changed@example.com"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            from db_models import User

            user = db.session.get(User, self.user_id)
            self.assertEqual(user.email, "changed@example.com")

    def test_admin_delete_user_blocks_owned_leagues(self):
        self.login_as(self.admin_id)
        with self.app.app_context():
            from db_models import League, LeagueMembership

            owned_league = League(
                name="Manager Owned Poker",
                slug="manager-owned-poker",
                public_key="mgr123",
                created_by_user_id=self.manager_id,
                visibility="private",
            )
            db.session.add(owned_league)
            db.session.flush()
            db.session.add(LeagueMembership(league_id=owned_league.id, user_id=self.manager_id, role="owner"))
            db.session.commit()

        response = self.client.post(
            f"/internal/users/{self.manager_id}/delete",
            data={"confirm": "DELETE"},
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            from db_models import User

            self.assertIsNotNone(db.session.get(User, self.manager_id))

    def test_admin_can_archive_and_restore_league(self):
        self.login_as(self.admin_id)

        archive_response = self.client.post(f"/internal/leagues/{self.league_id}/archive")
        self.assertEqual(archive_response.status_code, 302)
        with self.app.app_context():
            from db_models import League

            league = db.session.get(League, self.league_id)
            self.assertIsNotNone(league.archived_at)

        restore_response = self.client.post(f"/internal/leagues/{self.league_id}/restore")
        self.assertEqual(restore_response.status_code, 302)
        with self.app.app_context():
            from db_models import League

            league = db.session.get(League, self.league_id)
            self.assertIsNone(league.archived_at)

    def test_admin_can_update_league_settings(self):
        self.login_as(self.admin_id)

        response = self.client.post(
            f"/internal/leagues/{self.league_id}/settings",
            data={
                "name": "Saturday Poker",
                "description": "Updated by support",
                "visibility": "private",
                "eligible_min_sessions": "5",
                "break_even_dollars": "2.50",
            },
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            from db_models import League

            league = db.session.get(League, self.league_id)
            self.assertEqual(league.name, "Saturday Poker")
            self.assertEqual(league.slug, "saturday-poker")
            self.assertEqual(league.description, "Updated by support")
            self.assertEqual(league.visibility, "private")
            self.assertEqual(league.eligible_min_sessions, 5)
            self.assertEqual(league.break_even_cents, 250)

    def test_admin_can_transfer_league_ownership(self):
        self.login_as(self.admin_id)

        response = self.client.post(
            f"/internal/leagues/{self.league_id}/transfer",
            data={"new_owner_email": "manager@example.com"},
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            from db_models import League, LeagueMembership

            league = db.session.get(League, self.league_id)
            self.assertEqual(league.created_by_user_id, self.manager_id)
            old_owner_membership = LeagueMembership.query.filter_by(
                league_id=self.league_id,
                user_id=self.admin_id,
            ).one()
            new_owner_membership = LeagueMembership.query.filter_by(
                league_id=self.league_id,
                user_id=self.manager_id,
            ).one()
            self.assertEqual(old_owner_membership.role, "manager")
            self.assertEqual(new_owner_membership.role, "owner")


if __name__ == "__main__":
    unittest.main()
