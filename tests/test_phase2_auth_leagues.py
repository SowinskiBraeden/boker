from __future__ import annotations

from datetime import date
import unittest

from boker.db import database_extensions_available


@unittest.skipUnless(
    database_extensions_available(),
    "Database dependencies are not installed.",
)
class Phase2AuthLeagueRouteTests(unittest.TestCase):
    def setUp(self):
        from app import create_app
        from boker.db import db

        self.db = db
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.db.engine.dispose()
        self.ctx.pop()

    def league_path(self, league=None) -> str:
        if league is None:
            from boker.db_models import League

            league = League.query.one()
        return f"/l/{league.url_ref}"

    def create_verified_user(self, email="owner@example.com"):
        from boker.db_models import utc_now
        from boker.league_repositories import create_user

        user = create_user(email, "password123")
        self.db.session.flush()
        user.email_verified_at = utc_now()
        self.db.session.commit()
        return user

    def login_as(self, user):
        with self.client.session_transaction() as flask_session:
            flask_session["user_id"] = user.id

    def create_logged_in_league(self, email="owner@example.com", name="Friday Poker"):
        from boker.league_repositories import create_league

        owner = self.create_verified_user(email)
        league = create_league(owner, name, name.lower().replace(" ", "-"))
        self.db.session.commit()
        self.login_as(owner)
        return owner, league, self.league_path(league)

    def test_registration_starts_email_verification_before_login(self):
        from boker.db_models import User

        response = self.client.post(
            "/account/register",
            data={
                "email": "Owner@Example.com",
                "password": "password123",
                "confirm_password": "password123",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/account/verify-email")

        user = User.query.one()
        self.assertEqual(user.email, "owner@example.com")
        self.assertIsNone(user.email_verified_at)
        self.assertIsNotNone(user.email_verification_code_hash)

        with self.client.session_transaction() as flask_session:
            self.assertNotIn("user_id", flask_session)
            self.assertEqual(flask_session["pending_verification_user_id"], user.id)

    def test_verified_user_can_create_league_and_owner_membership(self):
        from boker.db_models import League, LeagueMembership, User

        user = self.create_verified_user("Owner@Example.com")
        self.login_as(user)

        response = self.client.post(
            "/leagues/new",
            data={
                "name": "Friday Poker",
                "slug": "",
                "description": "Private home league",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.assertEqual(User.query.count(), 1)
        league = League.query.one()
        self.assertEqual(response.headers["Location"], self.league_path(league))
        membership = LeagueMembership.query.one()
        self.assertEqual(league.slug, "friday-poker")
        self.assertEqual(membership.user_id, user.id)
        self.assertEqual(membership.role, "owner")

        dashboard = self.client.get(self.league_path(league))
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Friday Poker", dashboard.data)

    def test_legacy_admin_routes_are_not_registered_by_default(self):
        response = self.client.get("/admin/login")
        self.assertEqual(response.status_code, 404)

    def test_legacy_csv_public_routes_are_not_registered(self):
        for path in ("/leaderboard", "/sessions", "/sessions/legacy-session", "/players/Legacy"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)

    def test_duplicate_league_slug_is_allowed_because_route_uses_public_key(self):
        owner = self.create_verified_user()
        self.login_as(owner)
        self.client.post("/leagues/new", data={"name": "Friday Poker"})
        self.client.post("/leagues/new", data={"name": "Friday Poker"})

        from boker.db_models import League

        self.assertEqual(
            [league.slug for league in League.query.order_by(League.slug.asc()).all()],
            ["friday-poker", "friday-poker"],
        )

    def test_legacy_uuid_league_route_redirects_to_public_key_route(self):
        from boker.db import db
        from boker.league_repositories import create_league, create_user

        owner = create_user("owner@example.com", "password123")
        db.session.flush()
        league = create_league(owner, "Private League", "private-league")
        db.session.commit()

        with self.client.session_transaction() as flask_session:
            flask_session["user_id"] = owner.id

        response = self.client.get(f"/l/{league.id}/{league.slug}")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], self.league_path(league))

    def test_league_dashboard_requires_membership(self):
        from boker.db import db
        from boker.league_repositories import create_league, create_user

        owner = create_user("owner@example.com", "password123")
        other = create_user("other@example.com", "password123")
        db.session.flush()
        league = create_league(owner, "Private League", "private-league")
        db.session.commit()

        with self.client.session_transaction() as flask_session:
            flask_session["user_id"] = other.id

        response = self.client.get(self.league_path(league))
        self.assertEqual(response.status_code, 403)

    def test_owner_can_add_archive_and_reactivate_player(self):
        from boker.db_models import Player

        _, _, league_base = self.create_logged_in_league()

        response = self.client.post(
            f"{league_base}/players",
            data={
                "display_name": "Alex",
                "slug": "",
                "notes": "Usually hosts.",
            },
        )
        self.assertEqual(response.status_code, 302)

        player = Player.query.one()
        self.assertEqual(player.display_name, "Alex")
        self.assertEqual(player.slug, "alex")
        self.assertEqual(player.status, "active")
        self.assertEqual(player.notes, "Usually hosts.")

        duplicate = self.client.post(
            f"{league_base}/players",
            data={"display_name": " alex "},
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn(b"already exists", duplicate.data)
        self.assertEqual(Player.query.count(), 1)

        archive = self.client.post(f"{league_base}/players/{player.id}/archive")
        self.assertEqual(archive.status_code, 302)
        self.db.session.refresh(player)
        self.assertEqual(player.status, "archived")

        reactivate = self.client.post(f"{league_base}/players/{player.id}/reactivate")
        self.assertEqual(reactivate.status_code, 302)
        self.db.session.refresh(player)
        self.assertEqual(player.status, "active")

    def test_viewer_can_view_players_but_cannot_add_or_archive(self):
        from boker.db import db
        from boker.db_models import LeagueMembership, Player
        from boker.league_repositories import create_league, create_player, create_user

        owner = create_user("owner@example.com", "password123")
        viewer = create_user("viewer@example.com", "password123")
        db.session.flush()
        league = create_league(owner, "Private League", "private-league")
        player = create_player(league.id, "Alex", "alex")
        db.session.flush()
        db.session.add(
            LeagueMembership(
                league_id=league.id,
                user_id=viewer.id,
                role="viewer",
            )
        )
        db.session.commit()

        with self.client.session_transaction() as flask_session:
            flask_session["user_id"] = viewer.id

        league_base = self.league_path(league)
        response = self.client.get(f"{league_base}/players")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Alex", response.data)
        self.assertNotIn(b"Add player", response.data)

        add = self.client.post(
            f"{league_base}/players",
            data={"display_name": "Blair"},
        )
        self.assertEqual(add.status_code, 403)
        self.assertEqual(Player.query.count(), 1)

        archive = self.client.post(f"{league_base}/players/{player.id}/archive")
        self.assertEqual(archive.status_code, 403)
        self.db.session.refresh(player)
        self.assertEqual(player.status, "active")

    def test_owner_can_create_same_day_sessions_and_close_them(self):
        from boker.db_models import LedgerEvent, PokerSession

        _, _, league_base = self.create_logged_in_league()

        first = self.client.post(
            f"{league_base}/sessions",
            data={
                "session_date": "2026-10-02",
                "label": "",
                "status": "open",
                "notes": "Main game",
            },
        )
        second = self.client.post(
            f"{league_base}/sessions",
            data={
                "session_date": "2026-10-02",
                "label": "Late table",
                "status": "open",
            },
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)

        sessions = PokerSession.query.order_by(PokerSession.sequence_on_date.asc()).all()
        self.assertEqual([session.sequence_on_date for session in sessions], [1, 2])
        self.assertEqual(sessions[0].status, "open")
        self.assertEqual(sessions[0].notes, "Main game")
        self.assertEqual(sessions[1].display_label, "Late table")

        events = LedgerEvent.query.order_by(LedgerEvent.created_at.asc()).all()
        self.assertEqual([event.event_type for event in events], ["session_open", "session_open"])

        close = self.client.post(f"{league_base}/sessions/{sessions[0].id}/close")
        self.assertEqual(close.status_code, 302)
        self.db.session.refresh(sessions[0])
        self.assertEqual(sessions[0].status, "closed")
        self.assertIsNotNone(sessions[0].closed_at)
        self.assertEqual(LedgerEvent.query.count(), 3)
        self.assertEqual(
            LedgerEvent.query.order_by(LedgerEvent.created_at.desc()).first().event_type,
            "session_close",
        )

    def test_closed_session_creation_does_not_append_marker_event_until_opened(self):
        from boker.db_models import LedgerEvent, PokerSession

        _, _, league_base = self.create_logged_in_league()
        self.client.post(
            f"{league_base}/sessions",
            data={"session_date": "2026-10-02", "status": "closed"},
        )

        session = PokerSession.query.one()
        self.assertEqual(session.status, "closed")
        self.assertEqual(LedgerEvent.query.count(), 0)

        open_response = self.client.post(f"{league_base}/sessions/{session.id}/open")
        self.assertEqual(open_response.status_code, 302)
        self.db.session.refresh(session)
        self.assertEqual(session.status, "open")
        self.assertIsNotNone(session.opened_at)
        self.assertEqual(LedgerEvent.query.one().event_type, "session_open")

    def test_viewer_can_view_sessions_but_cannot_create_or_close(self):
        from boker.db import db
        from boker.db_models import LeagueMembership, PokerSession
        from boker.league_repositories import create_league, create_poker_session, create_user

        owner = create_user("owner@example.com", "password123")
        viewer = create_user("viewer@example.com", "password123")
        db.session.flush()
        league = create_league(owner, "Private League", "private-league")
        session = create_poker_session(league.id, date(2026, 10, 2), status="open")
        db.session.flush()
        db.session.add(
            LeagueMembership(
                league_id=league.id,
                user_id=viewer.id,
                role="viewer",
            )
        )
        db.session.commit()

        with self.client.session_transaction() as flask_session:
            flask_session["user_id"] = viewer.id

        league_base = self.league_path(league)
        response = self.client.get(f"{league_base}/sessions")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"2026-10-02", response.data)
        self.assertNotIn(b"Create session", response.data)

        create = self.client.post(
            f"{league_base}/sessions",
            data={"session_date": "2026-10-03"},
        )
        self.assertEqual(create.status_code, 403)
        self.assertEqual(PokerSession.query.count(), 1)

        close = self.client.post(f"{league_base}/sessions/{session.id}/close")
        self.assertEqual(close.status_code, 403)
        self.db.session.refresh(session)
        self.assertEqual(session.status, "open")

    def test_owner_can_append_events_and_view_db_backed_stats(self):
        from boker.db_models import LedgerEvent, Player, PokerSession

        _, _, league_base = self.create_logged_in_league()
        self.client.post(f"{league_base}/players", data={"display_name": "Alex"})
        self.client.post(
            f"{league_base}/sessions",
            data={"session_date": "2026-10-02", "status": "open"},
        )

        player = Player.query.one()
        session = PokerSession.query.one()

        buyin = self.client.post(
            f"{league_base}/sessions/{session.id}",
            data={
                "player_id": player.id,
                "event_type": "buyin",
                "amount": "20",
            },
        )
        cashout = self.client.post(
            f"{league_base}/sessions/{session.id}",
            data={
                "player_id": player.id,
                "event_type": "cashout",
                "amount": "35",
            },
        )
        paid = self.client.post(
            f"{league_base}/sessions/{session.id}",
            data={
                "player_id": player.id,
                "event_type": "paid_out",
                "amount": "15",
            },
        )

        self.assertEqual(buyin.status_code, 302)
        self.assertEqual(cashout.status_code, 302)
        self.assertEqual(paid.status_code, 302)
        self.assertEqual(LedgerEvent.query.filter_by(player_id=player.id).count(), 3)

        leaderboard = self.client.get(f"{league_base}/leaderboard")
        self.assertEqual(leaderboard.status_code, 200)
        self.assertIn(b"Alex", leaderboard.data)
        self.assertIn(b"15.00", leaderboard.data)

        detail = self.client.get(f"{league_base}/sessions/{session.id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"cashout", detail.data)
        self.assertIn(b"paid out", detail.data)

        player_detail = self.client.get(f"{league_base}/players/{player.id}")
        self.assertEqual(player_detail.status_code, 200)
        self.assertIn(b"Total net", player_detail.data)
        self.assertIn(b"20.00", player_detail.data)

    def test_league_ledger_shows_and_resolves_player_debts(self):
        from boker.db_models import LedgerEvent, Player, PokerSession

        _, _, league_base = self.create_logged_in_league()
        self.client.post(f"{league_base}/players", data={"display_name": "Alex"})
        self.client.post(
            f"{league_base}/sessions",
            data={"session_date": "2026-10-02", "status": "open"},
        )

        player = Player.query.one()
        session = PokerSession.query.one()
        self.client.post(
            f"{league_base}/sessions/{session.id}",
            data={"player_id": player.id, "event_type": "front", "amount": "50"},
        )
        self.client.post(
            f"{league_base}/sessions/{session.id}",
            data={"player_id": player.id, "event_type": "cashout", "amount": "20"},
        )

        ledger = self.client.get(f"{league_base}/ledger")
        self.assertEqual(ledger.status_code, 200)
        self.assertIn(b"Debt resolution", ledger.data)
        self.assertIn(b"Front receivables", ledger.data)
        self.assertIn(b"30.00", ledger.data)

        repayment = self.client.post(
            f"{league_base}/ledger",
            data={
                "session_id": session.id,
                "player_id": player.id,
                "event_type": "debt_repayment",
                "amount": "10",
            },
        )
        self.assertEqual(repayment.status_code, 302)
        self.assertEqual(
            LedgerEvent.query.order_by(LedgerEvent.created_at.desc()).first().event_type,
            "debt_repayment",
        )

        ledger = self.client.get(f"{league_base}/ledger")
        self.assertEqual(ledger.status_code, 200)
        self.assertIn(b"20.00", ledger.data)

    def test_viewer_cannot_append_ledger_events(self):
        from boker.db import db
        from boker.db_models import LeagueMembership, LedgerEvent
        from boker.league_repositories import (
            create_league,
            create_player,
            create_poker_session,
            create_user,
        )

        owner = create_user("owner@example.com", "password123")
        viewer = create_user("viewer@example.com", "password123")
        db.session.flush()
        league = create_league(owner, "Private League", "private-league")
        player = create_player(league.id, "Alex", "alex")
        session = create_poker_session(league.id, date(2026, 10, 2), status="open")
        db.session.flush()
        db.session.add(
            LeagueMembership(
                league_id=league.id,
                user_id=viewer.id,
                role="viewer",
            )
        )
        db.session.commit()

        with self.client.session_transaction() as flask_session:
            flask_session["user_id"] = viewer.id

        response = self.client.post(
            f"{self.league_path(league)}/sessions/{session.id}",
            data={
                "player_id": player.id,
                "event_type": "buyin",
                "amount": "20",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(LedgerEvent.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
