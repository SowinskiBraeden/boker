import unittest

from stats import SessionEntry, SessionSummary, build_leaderboard


class CashInAccountingTest(unittest.TestCase):
    def test_front_recovered_from_cashout_counts_as_session_cash_in(self):
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
        self.assertEqual(session.total_front_collected_cents, 0)
        self.assertEqual(session.total_cash_in_cents, 3000)

    def test_collected_front_shortfall_counts_as_session_cash_in(self):
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
        self.assertEqual(session.total_cash_in_cents, 1000)

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

    def test_leaderboard_cash_in_includes_collected_fronts(self):
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
                    cash_out_cents=4000,
                )
            ],
        )

        player = build_leaderboard([session])[0]

        self.assertEqual(player.total_buy_in_cents, 2500)
        self.assertEqual(player.total_front_collected_cents, 0)
        self.assertEqual(player.total_cash_in_cents, 3000)


if __name__ == "__main__":
    unittest.main()
