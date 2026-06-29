from __future__ import annotations

from datetime import date
import unittest

from boker.db import database_extensions_available


@unittest.skipUnless(
    database_extensions_available(),
    "Database dependencies are not installed.",
)
class DatabaseFoundationTests(unittest.TestCase):
    def setUp(self):
        from app import create_app
        from boker.db import db

        self.db = db
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            }
        )
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.db.create_all()

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.db.engine.dispose()
        self.ctx.pop()

    def test_owner_league_players_sessions_season_and_events(self):
        from boker.db_models import LedgerEvent, LeagueMembership, PokerSession
        from boker.ledger_repositories import append_ledger_event
        from boker.league_repositories import (
            create_league,
            create_player,
            create_poker_session,
            create_season,
            create_user,
            user_has_league_role,
        )

        owner = create_user("Owner@Example.com", "correct horse battery staple")
        self.db.session.flush()
        league = create_league(owner, "Friday Poker", "friday-poker")
        player = create_player(league.id, "Alex", "alex")
        season = create_season(
            league.id,
            "Fall 2026",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 12, 31),
        )
        self.db.session.flush()

        first_session = create_poker_session(
            league.id,
            date(2026, 10, 2),
            season_id=season.id,
            status="open",
        )
        second_session = create_poker_session(
            league.id,
            date(2026, 10, 2),
            season_id=season.id,
        )
        self.db.session.flush()

        append_ledger_event(
            league.id,
            first_session.id,
            "buyin",
            2500,
            owner.id,
            player_id=player.id,
        )
        append_ledger_event(
            league.id,
            first_session.id,
            "paid",
            1000,
            owner.id,
            player_id=player.id,
        )
        append_ledger_event(
            league.id,
            first_session.id,
            "session_close",
            9999,
            owner.id,
            note="Closed after payout review.",
        )
        self.db.session.commit()

        membership = LeagueMembership.query.filter_by(
            league_id=league.id,
            user_id=owner.id,
        ).one()
        sessions = PokerSession.query.order_by(PokerSession.sequence_on_date.asc()).all()
        events = LedgerEvent.query.order_by(LedgerEvent.created_at.asc()).all()

        self.assertEqual(owner.email, "owner@example.com")
        self.assertEqual(membership.role, "owner")
        self.assertTrue(user_has_league_role(owner.id, league.id, {"owner"}))
        self.assertEqual([s.sequence_on_date for s in sessions], [1, 2])
        self.assertEqual(sessions[0].season_id, season.id)
        self.assertEqual(events[1].event_type, "paid_out")
        self.assertEqual(events[2].amount_cents, 0)


if __name__ == "__main__":
    unittest.main()
