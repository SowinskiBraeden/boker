#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionEntry:
    session_id: str
    session_date: str
    player_name: str
    buy_in_cents: int = 0
    front_cents: int = 0
    front_collected_cents: int = 0
    front_writeoff_cents: int = 0
    cash_out_cents: int = 0
    paid_cents: int = 0
    rollover_in_cents: int = 0
    payout_carry_in_cents: int = 0
    rollover_out_cents: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def invested_cents(self) -> int:
        # Poker performance: money/chips that entered play. This is intentionally
        # broader than real cash because fronts and rollover-ins affect results.
        return self.buy_in_cents + self.front_cents + self.rollover_in_cents

    @property
    def net_cents(self) -> int:
        return self.cash_out_cents - self.invested_cents

    @property
    def paid_out_cents(self) -> int:
        return self.paid_cents

    @property
    def debt_repayment_cents(self) -> int:
        return self.front_collected_cents

    @property
    def writeoff_cents(self) -> int:
        return self.front_writeoff_cents

    @property
    def gross_payout_cents(self) -> int:
        # Settlement: cashout is a gross chip count/result, not proof that cash
        # was paid. Fronts are recovered from the cashout before the player has
        # a claim against the house.
        return max(self.cash_out_cents - self.front_cents, 0)

    @property
    def player_owes_gross_cents(self) -> int:
        return max(self.front_cents - self.cash_out_cents, 0)

    @property
    def gross_due_to_house_cents(self) -> int:
        return self.player_owes_gross_cents

    @property
    def settled_to_player_cents(self) -> int:
        # Rollover-out resolves the source session's payable even though it is
        # not real cash out. The destination session records it as rollover-in.
        return self.paid_out_cents + self.rollover_out_cents

    @property
    def current_due_to_player_cents(self) -> int:
        return max(
            self.gross_payout_cents
            + self.payout_carry_in_cents
            - self.settled_to_player_cents,
            0,
        )

    @property
    def settled_to_house_cents(self) -> int:
        # Front collections are real cash in. Writeoffs are not cash, but they
        # do resolve the receivable.
        return self.debt_repayment_cents + self.writeoff_cents

    @property
    def current_due_to_house_cents(self) -> int:
        return max(self.gross_due_to_house_cents - self.settled_to_house_cents, 0)

    @property
    def real_cash_in_cents(self) -> int:
        return self.buy_in_cents + self.debt_repayment_cents

    @property
    def real_cash_out_cents(self) -> int:
        return self.paid_out_cents

    @property
    def payout_due_cents(self) -> int:
        return self.gross_payout_cents

    @property
    def payout_remaining_cents(self) -> int:
        return self.current_due_to_player_cents

    @property
    def settled_cents(self) -> int:
        return self.settled_to_player_cents

    @property
    def current_due_cents(self) -> int:
        return self.current_due_to_player_cents

    @property
    def player_owes_cents(self) -> int:
        return self.current_due_to_house_cents

    @property
    def raw_player_owes_cents(self) -> int:
        return self.gross_due_to_house_cents

    @property
    def front_shortfall_cents(self) -> int:
        return self.gross_due_to_house_cents

    @property
    def overpaid_front_cents(self) -> int:
        return 0

    @property
    def front_writeoff_applied_cents(self) -> int:
        return min(
            self.writeoff_cents,
            max(self.gross_due_to_house_cents - self.front_collected_applied_cents, 0),
        )

    @property
    def front_collected_applied_cents(self) -> int:
        return min(self.debt_repayment_cents, self.gross_due_to_house_cents)

    @property
    def front_resolved_cents(self) -> int:
        return min(self.settled_to_house_cents, self.gross_due_to_house_cents)

    @property
    def payout_status(self) -> str:
        if self.current_due_to_house_cents > 0:
            return "owes"
        if self.writeoff_cents > 0:
            return "written_off"
        if self.debt_repayment_cents > 0:
            return "collected"
        if self.gross_payout_cents <= 0:
            return "none"
        if self.current_due_to_player_cents <= 0:
            if self.paid_out_cents < self.gross_payout_cents:
                return "settled"
            return "paid"
        if self.settled_to_player_cents <= 0:
            return "unpaid"
        return "partial"


@dataclass
class SessionSummary:
    session_id: str
    session_date: str
    entries: list[SessionEntry]
    status: str = "closed"
    opened_at: str = ""

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def total_buy_in_cents(self) -> int:
        return sum(entry.buy_in_cents for entry in self.entries)

    @property
    def total_front_cents(self) -> int:
        return sum(entry.front_cents for entry in self.entries)

    @property
    def total_rollover_in_cents(self) -> int:
        return sum(entry.rollover_in_cents for entry in self.entries)

    @property
    def total_payout_carry_in_cents(self) -> int:
        return sum(entry.payout_carry_in_cents for entry in self.entries)

    @property
    def total_invested_cents(self) -> int:
        return sum(entry.invested_cents for entry in self.entries)

    @property
    def total_cash_out_cents(self) -> int:
        return sum(entry.cash_out_cents for entry in self.entries)

    @property
    def total_payout_due_cents(self) -> int:
        return self.total_gross_payout_cents

    @property
    def total_remaining_cents(self) -> int:
        return self.total_current_due_to_player_cents

    @property
    def total_net_cents(self) -> int:
        return sum(entry.net_cents for entry in self.entries)

    @property
    def total_gross_payout_cents(self) -> int:
        return sum(entry.gross_payout_cents for entry in self.entries)

    @property
    def total_paid_cents(self) -> int:
        return self.total_paid_out_cents

    @property
    def total_paid_out_cents(self) -> int:
        return sum(entry.paid_out_cents for entry in self.entries)

    @property
    def total_rollover_out_cents(self) -> int:
        return sum(entry.rollover_out_cents for entry in self.entries)

    @property
    def total_settled_to_player_cents(self) -> int:
        return sum(entry.settled_to_player_cents for entry in self.entries)

    @property
    def total_current_due_to_player_cents(self) -> int:
        return sum(entry.current_due_to_player_cents for entry in self.entries)

    @property
    def total_player_owes_gross_cents(self) -> int:
        return sum(entry.gross_due_to_house_cents for entry in self.entries)

    @property
    def total_gross_due_to_house_cents(self) -> int:
        return self.total_player_owes_gross_cents

    @property
    def total_settled_to_house_cents(self) -> int:
        return sum(entry.settled_to_house_cents for entry in self.entries)

    @property
    def total_current_due_to_house_cents(self) -> int:
        return sum(entry.current_due_to_house_cents for entry in self.entries)

    @property
    def total_front_writeoff_cents(self) -> int:
        return self.total_writeoff_cents

    @property
    def total_front_collected_cents(self) -> int:
        return self.total_debt_repayment_cents

    @property
    def total_debt_repayment_cents(self) -> int:
        return sum(entry.debt_repayment_cents for entry in self.entries)

    @property
    def total_writeoff_cents(self) -> int:
        return sum(entry.writeoff_cents for entry in self.entries)

    @property
    def total_cash_in_cents(self) -> int:
        return sum(entry.real_cash_in_cents for entry in self.entries)

    @property
    def total_real_cash_in_cents(self) -> int:
        return self.total_cash_in_cents

    @property
    def total_real_cash_out_cents(self) -> int:
        return self.total_paid_out_cents

    @property
    def total_banker_cash_in_cents(self) -> int:
        return self.total_real_cash_in_cents

    @property
    def total_banker_cash_out_cents(self) -> int:
        return self.total_real_cash_out_cents

    @property
    def total_current_due_cents(self) -> int:
        return self.total_current_due_to_player_cents

    @property
    def total_player_owes_cents(self) -> int:
        return self.total_current_due_to_house_cents

    @property
    def total_open_balance_cents(self) -> int:
        return self.total_current_due_to_player_cents - self.total_current_due_to_house_cents

    @property
    def total_net_book_position_cents(self) -> int:
        # Banker view: cash currently held, plus collectible receivables, minus
        # unpaid player claims. Rollover-outs reduce payables but are not cash.
        return (
            self.total_cash_in_cents
            - self.total_paid_out_cents
            + self.total_current_due_to_house_cents
            - self.total_current_due_to_player_cents
        )


@dataclass
class PlayerStats:
    player_name: str
    sessions_played: int
    winning_sessions: int
    losing_sessions: int
    break_even_sessions: int
    win_pct: float
    avg_win_cents: int
    avg_loss_cents: int
    biggest_win_cents: int
    biggest_loss_cents: int
    total_buy_in_cents: int
    total_front_cents: int
    total_front_collected_cents: int
    total_front_writeoff_cents: int
    current_player_owes_cents: int
    total_rollover_in_cents: int
    total_payout_carry_in_cents: int
    total_invested_cents: int
    total_cash_out_cents: int
    total_gross_payout_cents: int
    total_paid_cents: int
    total_rollover_out_cents: int
    current_due_to_player_cents: int
    total_net_cents: int
    roi_pct: float
    current_win_streak: int
    current_loss_streak: int
    longest_win_streak: int
    longest_loss_streak: int
    best_session_date: str | None
    best_session_net_cents: int
    worst_session_date: str | None
    worst_session_net_cents: int
    rank_change: int = 0

    @property
    def total_debt_repayment_cents(self) -> int:
        return self.total_front_collected_cents

    @property
    def total_writeoff_cents(self) -> int:
        return self.total_front_writeoff_cents

    @property
    def current_due_to_house_cents(self) -> int:
        return self.current_player_owes_cents

    @property
    def total_paid_out_cents(self) -> int:
        return self.total_paid_cents

    @property
    def total_real_cash_out_cents(self) -> int:
        return self.total_paid_out_cents

    @property
    def total_real_cash_in_cents(self) -> int:
        return self.total_buy_in_cents + self.total_debt_repayment_cents
