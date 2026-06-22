import unittest

from stats import build_session_summaries


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
                event("s1", "2026-01-01", "A", "paid", 20, 3),
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
                event("s1", "2026-01-01", "A", "paid", 3, 3),
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

    def test_debt_repayment_and_writeoff_resolve_front_without_inflating_cash(self):
        session, entry = self.entry_for(
            [
                event("s1", "2026-01-01", "A", "front", 10, 1),
                event("s1", "2026-01-01", "A", "cashout", 0, 2),
                event("s1", "2026-01-01", "A", "front_collected", 6, 3),
                event("s1", "2026-01-01", "A", "front_writeoff", 4, 4),
            ]
        )

        self.assertEqual(entry.player_owes_gross_cents, cents(10))
        self.assertEqual(entry.current_due_to_house_cents, 0)
        self.assertEqual(session.total_cash_in_cents, cents(6))
        self.assertEqual(session.total_front_writeoff_cents, cents(4))


if __name__ == "__main__":
    unittest.main()
