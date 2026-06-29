import unittest

from boker.models import SessionEntry, SessionSummary
from boker.services import build_leaderboard


class CashInAccountingTest(unittest.TestCase):
    def test_front_is_poker_investment_not_cash_in(self):
        entry = SessionEntry(
            session_id="2026-06-21-01",
            session_date="2026-06-21",
            player_name="Alex",
            buy_in_cents=2500,
            front_cents=500,
            cash_out_cents=4000,
        )
        session = SessionSummary(
            session_id="2026-06-21-01",
            session_date="2026-06-21",
            entries=[entry],
        )

        self.assertEqual(session.total_buy_in_cents, 2500)
        self.assertEqual(session.total_front_cents, 500)
        self.assertEqual(session.total_cash_in_cents, 2500)

    def test_debt_repayment_counts_as_session_cash_in(self):
        entry = SessionEntry(
            session_id="2026-06-21-01",
            session_date="2026-06-21",
            player_name="Alex",
            front_cents=1000,
            cash_out_cents=400,
            front_collected_cents=600,
        )
        session = SessionSummary(
            session_id="2026-06-21-01",
            session_date="2026-06-21",
            entries=[entry],
        )

        self.assertEqual(session.total_front_collected_cents, 600)
        self.assertEqual(session.total_cash_in_cents, 600)

    def test_written_off_front_does_not_count_as_session_cash_in(self):
        entry = SessionEntry(
            session_id="2026-06-21-01",
            session_date="2026-06-21",
            player_name="Blair",
            front_cents=1000,
            front_writeoff_cents=1000,
        )
        session = SessionSummary(
            session_id="2026-06-21-01",
            session_date="2026-06-21",
            entries=[entry],
        )

        self.assertEqual(session.total_front_writeoff_cents, 1000)
        self.assertEqual(session.total_cash_in_cents, 0)

    def test_leaderboard_cash_in_uses_real_cash_only(self):
        session = SessionSummary(
            session_id="2026-06-21-01",
            session_date="2026-06-21",
            entries=[
                SessionEntry(
                    session_id="2026-06-21-01",
                    session_date="2026-06-21",
                    player_name="Alex",
                    buy_in_cents=2500,
                    front_cents=500,
                    front_collected_cents=200,
                    cash_out_cents=4000,
                )
            ],
        )

        player = build_leaderboard([session])[0]

        self.assertEqual(player.total_buy_in_cents, 2500)
        self.assertEqual(player.total_front_collected_cents, 200)
        self.assertEqual(player.total_real_cash_in_cents, 2700)


if __name__ == "__main__":
    unittest.main()
