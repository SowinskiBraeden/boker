import unittest

from boker.charts import player_session_series
from boker.services import (
    build_leaderboard,
    build_session_summaries,
    pending_payout_carry_items,
    prunable_empty_session_ids,
)
from boker.utils import session_sort_key


def cents(amount: float) -> int:
    return int(round(amount * 100))


def event(
    session_id: str,
    session_date: str,
    player_name: str,
    event_type: str,
    amount: float,
    index: int,
):
    return {
        "id": f"{session_id}-{index}",
        "created_at": f"2026-01-01T00:00:{index:02d}+00:00",
        "session_id": session_id,
        "session_date": session_date,
        "player_name": player_name,
        "event_type": event_type,
        "amount_cents": cents(amount),
        "note": "",
        "actor": "test",
    }


class AccountingTests(unittest.TestCase):
    def entry_for(self, rows, session_id="s1", player_name="A"):
        sessions = build_session_summaries(rows)
        session = next(s for s in sessions if s.session_id == session_id)
        entry = next(e for e in session.entries if e.player_name == player_name)
        return session, entry

    def test_buyin_cashout_and_paid_are_distinct(self):
        session, entry = self.entry_for(
            [
                event("s1", "2026-01-01", "A", "buyin", 10, 1),
                event("s1", "2026-01-01", "A", "cashout", 20, 2),
                event("s1", "2026-01-01", "A", "paid_out", 20, 3),
            ]
        )

        self.assertEqual(entry.invested_cents, cents(10))
        self.assertEqual(entry.net_cents, cents(10))
        self.assertEqual(session.total_cash_in_cents, cents(10))
        self.assertEqual(session.total_paid_out_cents, cents(20))
        self.assertEqual(entry.current_due_to_player_cents, 0)
        self.assertEqual(entry.current_due_to_house_cents, 0)

    def test_front_is_invested_but_not_cash_in_until_collected(self):
        session, entry = self.entry_for(
            [
                event("s1", "2026-01-01", "A", "front", 5, 1),
                event("s1", "2026-01-01", "A", "cashout", 8, 2),
                event("s1", "2026-01-01", "A", "paid_out", 3, 3),
            ]
        )

        self.assertEqual(entry.invested_cents, cents(5))
        self.assertEqual(entry.net_cents, cents(3))
        self.assertEqual(entry.gross_payout_cents, cents(3))
        self.assertEqual(entry.current_due_to_player_cents, 0)
        self.assertEqual(session.total_cash_in_cents, 0)
        self.assertEqual(session.total_paid_out_cents, cents(3))

    def test_rollover_out_reduces_source_session_payable_without_cash_out(self):
        session, entry = self.entry_for(
            [
                event("s1", "2026-01-01", "A", "buyin", 10, 1),
                event("s1", "2026-01-01", "A", "cashout", 19.50, 2),
                event("s1", "2026-01-01", "A", "rollover_out", 10, 3),
            ]
        )

        self.assertEqual(entry.net_cents, cents(9.50))
        self.assertEqual(entry.gross_payout_cents, cents(19.50))
        self.assertEqual(entry.current_due_to_player_cents, cents(9.50))
        self.assertEqual(session.total_paid_out_cents, 0)
        self.assertEqual(entry.payout_status, "partial")

    def test_rollover_in_is_invested_without_new_cash_in(self):
        rows = [
            event("s1", "2026-01-01", "A", "buyin", 10, 1),
            event("s1", "2026-01-01", "A", "cashout", 19.50, 2),
            event("s1", "2026-01-01", "A", "rollover_out", 10, 3),
            event("s2", "2026-01-02", "A", "rollover_in", 10, 4),
        ]
        sessions = build_session_summaries(rows)
        source = next(s for s in sessions if s.session_id == "s1")
        dest = next(s for s in sessions if s.session_id == "s2")
        dest_entry = dest.entries[0]

        self.assertEqual(sum(s.total_cash_in_cents for s in sessions), cents(10))
        self.assertEqual(source.total_current_due_to_player_cents, cents(9.50))
        self.assertEqual(dest_entry.invested_cents, cents(10))
        self.assertEqual(dest.total_cash_in_cents, 0)

    def test_payout_carry_in_does_not_count_as_investment_or_cash(self):
        rows = [
            event("s1", "2026-01-01", "A", "buyin", 10, 1),
            event("s1", "2026-01-01", "A", "payout_carry_in", 0.60, 2),
            event("s1", "2026-01-01", "A", "cashout", 6.55, 3),
            event("s1", "2026-01-01", "A", "paid_out", 6.55, 4),
        ]
        session, entry = self.entry_for(rows)
        player = build_leaderboard([session])[0]

        self.assertEqual(entry.payout_carry_in_cents, cents(0.60))
        self.assertEqual(entry.invested_cents, cents(10))
        self.assertEqual(entry.net_cents, cents(-3.45))
        self.assertEqual(entry.current_due_to_player_cents, cents(0.60))
        self.assertEqual(session.total_cash_in_cents, cents(10))
        self.assertEqual(player.total_payout_carry_in_cents, cents(0.60))

    def test_debt_repayment_and_writeoff_resolve_front_without_inflating_cash(self):
        session, entry = self.entry_for(
            [
                event("s1", "2026-01-01", "A", "front", 10, 1),
                event("s1", "2026-01-01", "A", "cashout", 0, 2),
                event("s1", "2026-01-01", "A", "debt_repayment", 6, 3),
                event("s1", "2026-01-01", "A", "writeoff", 4, 4),
            ]
        )

        self.assertEqual(entry.gross_due_to_house_cents, cents(10))
        self.assertEqual(entry.current_due_to_house_cents, 0)
        self.assertEqual(session.total_cash_in_cents, cents(6))
        self.assertEqual(session.total_writeoff_cents, cents(4))

    def test_banker_book_position_separates_cash_and_open_items(self):
        rows = [
            event("s1", "2026-01-01", "A", "buyin", 10, 1),
            event("s1", "2026-01-01", "A", "cashout", 25, 2),
            event("s1", "2026-01-01", "A", "paid_out", 5, 3),
            event("s1", "2026-01-01", "A", "rollover_out", 10, 4),
            event("s1", "2026-01-01", "B", "front", 20, 5),
            event("s1", "2026-01-01", "B", "cashout", 0, 6),
            event("s1", "2026-01-01", "B", "debt_repayment", 8, 7),
            event("s1", "2026-01-01", "B", "writeoff", 2, 8),
        ]
        sessions = build_session_summaries(rows)
        session = next(s for s in sessions if s.session_id == "s1")

        self.assertEqual(session.total_invested_cents, cents(30))
        self.assertEqual(session.total_cash_out_cents, cents(25))
        self.assertEqual(session.total_real_cash_in_cents, cents(18))
        self.assertEqual(session.total_real_cash_out_cents, cents(5))
        self.assertEqual(session.total_current_due_to_player_cents, cents(10))
        self.assertEqual(session.total_current_due_to_house_cents, cents(10))
        self.assertEqual(session.total_net_book_position_cents, cents(13))

    def test_player_stats_track_house_owes_player_separately_from_cash_paid(self):
        rows = [
            event("s1", "2026-01-01", "A", "buyin", 10, 1),
            event("s1", "2026-01-01", "A", "cashout", 25, 2),
            event("s1", "2026-01-01", "A", "paid_out", 5, 3),
        ]
        player = build_leaderboard(build_session_summaries(rows))[0]

        self.assertEqual(player.total_cash_out_cents, cents(25))
        self.assertEqual(player.total_gross_payout_cents, cents(25))
        self.assertEqual(player.total_paid_out_cents, cents(5))
        self.assertEqual(player.current_due_to_player_cents, cents(20))
        self.assertEqual(player.total_real_cash_out_cents, cents(5))

    def test_rollover_out_can_settle_without_being_marked_paid(self):
        rows = [
            event("s1", "2026-01-01", "A", "buyin", 10, 1),
            event("s1", "2026-01-01", "A", "cashout", 20, 2),
            event("s1", "2026-01-01", "A", "rollover_out", 20, 3),
        ]
        entry = build_session_summaries(rows)[0].entries[0]

        self.assertEqual(entry.current_due_to_player_cents, 0)
        self.assertEqual(entry.paid_out_cents, 0)
        self.assertEqual(entry.payout_status, "settled")

    def test_pending_payout_carry_in_preserves_poker_investment(self):
        rows = [
            event("s1", "2026-01-01", "", "session_open", 0, 1),
            event("s1", "2026-01-01", "A", "buyin", 10, 2),
            event("s1", "2026-01-01", "A", "cashout", 20, 3),
            event("s1", "2026-01-01", "A", "rollover_out", 5, 4),
            event("s1", "2026-01-01", "", "session_close", 0, 5),
            event("s2", "2026-01-02", "", "session_open", 0, 6),
            event("s2", "2026-01-02", "A", "buyin", 10, 7),
        ]

        sessions = build_session_summaries(rows)
        self.assertEqual(
            pending_payout_carry_items(sessions),
            [{"player_name": "A", "amount_cents": cents(5)}],
        )

        rows.append(event("s2", "2026-01-02", "A", "payout_carry_in", 5, 8))
        updated_sessions = build_session_summaries(rows)
        target = next(s for s in updated_sessions if s.session_id == "s2")
        target_entry = target.entries[0]
        self.assertEqual(target_entry.payout_carry_in_cents, cents(5))
        self.assertEqual(target_entry.invested_cents, cents(10))
        self.assertEqual(target_entry.current_due_to_player_cents, cents(5))

    def test_same_day_sessions_sort_by_session_sequence(self):
        rows = [
            event("2026-03-21-02", "2026-03-21", "A", "buyin", 10, 1),
            event("2026-03-21-02", "2026-03-21", "A", "cashout", 11, 2),
            event("2026-03-21-01", "2026-03-21", "A", "buyin", 10, 3),
            event("2026-03-21-01", "2026-03-21", "A", "cashout", 9, 4),
        ]
        sessions = build_session_summaries(rows)
        ordered = sorted(sessions, key=session_sort_key)

        self.assertEqual([s.session_id for s in ordered], ["2026-03-21-01", "2026-03-21-02"])
        self.assertEqual(
            player_session_series(sessions, "A")["labels"],
            ["Mar 21, 2026 · S1", "Mar 21, 2026 · S2"],
        )

    def test_prunable_empty_sessions_excludes_played_sessions(self):
        rows = [
            event("empty-1", "2026-01-01", "", "session_open", 0, 1),
            event("empty-1", "2026-01-01", "", "session_close", 0, 2),
            event("played-1", "2026-01-02", "", "session_open", 0, 3),
            event("played-1", "2026-01-02", "A", "buyin", 10, 4),
            event("played-1", "2026-01-02", "A", "cashout", 15, 5),
            event("played-1", "2026-01-02", "", "session_close", 0, 6),
        ]

        sessions = build_session_summaries(rows)
        prunable_ids = prunable_empty_session_ids(rows, sessions)
        self.assertEqual(prunable_ids, {"empty-1"})

        remaining = [
            row
            for row in rows
            if (row["session_id"].strip() or row["session_date"].strip())
            not in prunable_ids
        ]
        self.assertEqual({row["session_id"] for row in remaining}, {"played-1"})
        self.assertEqual(
            [row["event_type"] for row in remaining],
            ["session_open", "buyin", "cashout", "session_close"],
        )


if __name__ == "__main__":
    unittest.main()
