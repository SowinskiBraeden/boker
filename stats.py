#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from storage import EventRow

PLAYER_PALETTE = [
    "#f4a261",
    "#2a9d8f",
    "#8d99ae",
    "#e76f51",
    "#7c6cf2",
    "#84cc16",
    "#f59e0b",
    "#10b981",
    "#ef4444",
    "#06b6d4",
    "#a855f7",
    "#eab308",
]


@dataclass
class SessionEntry:
    session_id: str
    session_date: str
    player_name: str
    buy_in_cents: int = 0
    front_cents: int = 0
    cash_out_cents: int = 0
    paid_cents: int = 0
    rollover_in_cents: int = 0
    rollover_out_cents: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def invested_cents(self) -> int:
        return self.buy_in_cents + self.front_cents + self.rollover_in_cents

    @property
    def net_cents(self) -> int:
        return self.cash_out_cents - self.invested_cents

    @property
    def payout_due_cents(self) -> int:
        return max(self.cash_out_cents - self.front_cents, 0)

    @property
    def payout_remaining_cents(self) -> int:
        return max(self.payout_due_cents - self.paid_cents - self.rollover_out_cents, 0)

    @property
    def gross_payout_cents(self) -> int:
        return max(self.cash_out_cents - self.front_cents, 0)

    @property
    def settled_cents(self) -> int:
        return self.paid_cents + self.rollover_out_cents

    @property
    def current_due_cents(self) -> int:
        return max(self.gross_payout_cents - self.settled_cents, 0)

    @property
    def player_owes_cents(self) -> int:
        return max(self.front_cents - self.cash_out_cents, 0)

    @property
    def payout_status(self) -> str:
        if self.player_owes_cents > 0:
            return "owes"
        if self.gross_payout_cents <= 0:
            return "none"
        if self.current_due_cents <= 0:
            return "paid"
        if self.settled_cents <= 0:
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
    def total_invested_cents(self) -> int:
        return sum(entry.invested_cents for entry in self.entries)

    @property
    def total_cash_out_cents(self) -> int:
        return sum(entry.cash_out_cents for entry in self.entries)

    @property
    def total_payout_due_cents(self) -> int:
        return sum(entry.payout_due_cents for entry in self.entries)

    @property
    def total_remaining_cents(self) -> int:
        return sum(entry.payout_remaining_cents for entry in self.entries)

    @property
    def total_net_cents(self) -> int:
        return sum(entry.net_cents for entry in self.entries)

    @property
    def total_gross_payout_cents(self) -> int:
        return sum(entry.gross_payout_cents for entry in self.entries)

    @property
    def total_paid_cents(self) -> int:
        return sum(entry.paid_cents for entry in self.entries)

    @property
    def total_rollover_out_cents(self) -> int:
        return sum(entry.rollover_out_cents for entry in self.entries)

    @property
    def total_current_due_cents(self) -> int:
        return sum(entry.current_due_cents for entry in self.entries)

    @property
    def total_player_owes_cents(self) -> int:
        return sum(entry.player_owes_cents for entry in self.entries)

    @property
    def total_cash_in_cents(self) -> int:
        return sum(entry.buy_in_cents for entry in self.entries)

    @property
    def total_paid_out_cents(self) -> int:
        return sum(entry.paid_cents for entry in self.entries)

    @property
    def total_open_balance_cents(self) -> int:
        return self.total_current_due_cents - self.total_player_owes_cents


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
    total_rollover_in_cents: int
    total_invested_cents: int
    total_cash_out_cents: int
    total_paid_cents: int
    total_rollover_out_cents: int
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


def apply_rank_changes(
    current_board: list[PlayerStats], prev_board: list[PlayerStats]
) -> list[PlayerStats]:
    prev_ranks = {p.player_name: i for i, p in enumerate(prev_board, start=1)}

    for i, p in enumerate(current_board, start=1):
        prev_rank = prev_ranks.get(p.player_name)

        if prev_rank is None:
            p.rank_change = 0
        else:
            p.rank_change = prev_rank - i

    return current_board


def cents_to_dollars(cents: int) -> str:
    value = cents / 100
    return f"${value:,.2f}"


def session_sort_key(session: SessionSummary) -> tuple[str, int, str]:
    session_id = session.session_id.strip()

    if session_id == session.session_date:
        return (session.session_date, 1, session_id)

    suffix = session_id.replace(f"{session.session_date}-", "")
    if suffix.isdigit():
        return (session.session_date, int(suffix), session_id)

    if suffix.lower().startswith("s") and suffix[1:].isdigit():
        return (session.session_date, int(suffix[1:]), session_id)

    return (session.session_date, 9999, session_id)


def session_chart_label(session: SessionSummary) -> str:
    session_id = session.session_id.strip()

    if session_id == session.session_date:
        return safe_date_label(session.session_date)

    suffix = session_id.replace(f"{session.session_date}-", "")
    if suffix.isdigit():
        return f"{safe_date_label(session.session_date)} · S{int(suffix)}"

    if suffix.lower().startswith("s") and suffix[1:].isdigit():
        return f"{safe_date_label(session.session_date)} · S{int(suffix[1:])}"

    return f"{safe_date_label(session.session_date)} · {suffix}"


def safe_date_label(raw_date: str) -> str:
    try:
        return datetime.strptime(raw_date, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return raw_date


def session_label(session: SessionSummary) -> str:
    if session.session_id == session.session_date:
        return safe_date_label(session.session_date)

    suffix = session.session_id.replace(f"{session.session_date}-", "")
    if suffix.isdigit():
        return f"{safe_date_label(session.session_date)} · S{int(suffix)}"
    return f"{safe_date_label(session.session_date)} · {suffix}"


def color_for_name(name: str, names: list[str]) -> str:
    try:
        index = sorted(names, key=str.casefold).index(name)
    except ValueError:
        index = abs(hash(name))
    return PLAYER_PALETTE[index % len(PLAYER_PALETTE)]


def net_tone(value_cents: int) -> str:
    if value_cents > 0:
        return "#22c55e"
    if value_cents < 0:
        return "#ef4444"
    return "#f59e0b"


def build_session_summaries(events: list[EventRow]) -> list[SessionSummary]:
    grouped: dict[tuple[str, str], SessionEntry] = {}
    by_session: dict[str, list[SessionEntry]] = defaultdict(list)
    session_status: dict[str, str] = {}
    session_dates: dict[str, str] = {}
    session_opened_at: dict[str, str] = {}

    for event in events:
        session_id = event["session_id"].strip() or event["session_date"].strip()
        session_date = event["session_date"].strip()
        event_type = event["event_type"].strip()

        if not session_id or not session_date:
            continue

        session_dates[session_id] = session_date
        session_opened_at.setdefault(session_id, event["created_at"])

        if event_type == "session_open":
            session_status[session_id] = "open"
            continue

        if event_type == "session_close":
            session_status[session_id] = "closed"
            continue

        player_name = event["player_name"].strip()
        if not player_name:
            continue

        key = (session_id, player_name)
        if key not in grouped:
            grouped[key] = SessionEntry(
                session_id=session_id,
                session_date=session_date,
                player_name=player_name,
            )

        entry = grouped[key]

        if event_type == "buyin":
            entry.buy_in_cents += event["amount_cents"]
        elif event_type == "front":
            entry.front_cents += event["amount_cents"]
        elif event_type == "rollover_in":
            entry.rollover_in_cents += event["amount_cents"]
        elif event_type == "cashout":
            entry.cash_out_cents += event["amount_cents"]
        elif event_type == "paid":
            entry.paid_cents += event["amount_cents"]
        elif event_type == "rollover_out":
            entry.rollover_out_cents += event["amount_cents"]

        if event["note"]:
            entry.notes.append(event["note"])

    for entry in grouped.values():
        by_session[entry.session_id].append(entry)

    sessions: list[SessionSummary] = []
    for session_id, session_date in session_dates.items():
        entries = sorted(
            by_session.get(session_id, []),
            key=lambda entry: entry.player_name.casefold(),
        )

        sessions.append(
            SessionSummary(
                session_id=session_id,
                session_date=session_date,
                entries=entries,
                status=session_status.get(session_id, "closed"),
                opened_at=session_opened_at.get(session_id, ""),
            )
        )

    sessions.sort(
        key=lambda session: (
            session.session_date,
            session.opened_at,
            session.session_id,
        ),
        reverse=True,
    )
    return sessions


def summarize_player_runs(entries: list[SessionEntry]) -> dict[str, int | str | None]:
    ordered_entries = sorted(entries, key=lambda entry: entry.session_date)

    longest_win_streak = 0
    longest_loss_streak = 0
    current_run_wins = 0
    current_run_losses = 0

    best_entry: SessionEntry | None = None
    worst_entry: SessionEntry | None = None

    for entry in ordered_entries:
        net = entry.net_cents

        if best_entry is None or net > best_entry.net_cents:
            best_entry = entry

        if worst_entry is None or net < worst_entry.net_cents:
            worst_entry = entry

        if net > 0:
            current_run_wins += 1
            current_run_losses = 0
        elif net < 0:
            current_run_losses += 1
            current_run_wins = 0
        else:
            current_run_wins = 0
            current_run_losses = 0

        longest_win_streak = max(longest_win_streak, current_run_wins)
        longest_loss_streak = max(longest_loss_streak, current_run_losses)

    current_win_streak = 0
    current_loss_streak = 0

    for entry in reversed(ordered_entries):
        net = entry.net_cents

        if net > 0:
            if current_loss_streak > 0:
                break
            current_win_streak += 1
        elif net < 0:
            if current_win_streak > 0:
                break
            current_loss_streak += 1
        else:
            break

    return {
        "current_win_streak": current_win_streak,
        "current_loss_streak": current_loss_streak,
        "longest_win_streak": longest_win_streak,
        "longest_loss_streak": longest_loss_streak,
        "best_session_date": best_entry.session_date if best_entry else None,
        "best_session_net_cents": best_entry.net_cents if best_entry else 0,
        "worst_session_date": worst_entry.session_date if worst_entry else None,
        "worst_session_net_cents": worst_entry.net_cents if worst_entry else 0,
    }


def build_leaderboard(sessions: list[SessionSummary]) -> list[PlayerStats]:
    player_entries: dict[str, list[SessionEntry]] = defaultdict(list)
    for session in sessions:
        for entry in session.entries:
            player_entries[entry.player_name].append(entry)

    leaderboard: list[PlayerStats] = []
    for player_name, entries in player_entries.items():
        nets = [entry.net_cents for entry in entries]
        run_summary = summarize_player_runs(entries)
        wins = [value for value in nets if value > 0]
        losses = [value for value in nets if value < 0]

        sessions_played = len(entries)
        winning_sessions = len(wins)
        losing_sessions = len(losses)
        break_even_sessions = sessions_played - winning_sessions - losing_sessions
        win_pct = (winning_sessions / sessions_played * 100) if sessions_played else 0.0
        avg_win = round(sum(wins) / len(wins)) if wins else 0
        avg_loss = (
            round(sum(abs(value) for value in losses) / len(losses)) if losses else 0
        )
        biggest_win = max(wins) if wins else 0
        biggest_loss = min(losses) if losses else 0

        total_buy_in = sum(entry.buy_in_cents for entry in entries)
        total_front = sum(entry.front_cents for entry in entries)
        total_rollover_in = sum(entry.rollover_in_cents for entry in entries)
        total_invested = sum(entry.invested_cents for entry in entries)
        total_cash_out = sum(entry.cash_out_cents for entry in entries)
        total_paid = sum(entry.paid_cents for entry in entries)
        total_rollover_out = sum(entry.rollover_out_cents for entry in entries)
        total_net = sum(entry.net_cents for entry in entries)
        roi_pct = (total_net / total_invested * 100) if total_invested else 0.0

        leaderboard.append(
            PlayerStats(
                player_name=player_name,
                sessions_played=sessions_played,
                winning_sessions=winning_sessions,
                losing_sessions=losing_sessions,
                break_even_sessions=break_even_sessions,
                win_pct=win_pct,
                avg_win_cents=avg_win,
                avg_loss_cents=avg_loss,
                biggest_win_cents=biggest_win,
                biggest_loss_cents=biggest_loss,
                total_buy_in_cents=total_buy_in,
                total_front_cents=total_front,
                total_rollover_in_cents=total_rollover_in,
                total_invested_cents=total_invested,
                total_cash_out_cents=total_cash_out,
                total_paid_cents=total_paid,
                total_rollover_out_cents=total_rollover_out,
                total_net_cents=total_net,
                roi_pct=roi_pct,
                current_win_streak=run_summary["current_win_streak"],
                current_loss_streak=run_summary["current_loss_streak"],
                longest_win_streak=run_summary["longest_win_streak"],
                longest_loss_streak=run_summary["longest_loss_streak"],
                best_session_date=run_summary["best_session_date"],
                best_session_net_cents=run_summary["best_session_net_cents"],
                worst_session_date=run_summary["worst_session_date"],
                worst_session_net_cents=run_summary["worst_session_net_cents"],
            )
        )

    leaderboard.sort(
        key=lambda player: (player.total_net_cents, player.total_cash_out_cents),
        reverse=True,
    )
    return leaderboard


def cumulative_profit_series(sessions: list[SessionSummary]) -> dict[str, object]:
    ordered_sessions = sorted(sessions, key=session_sort_key)

    all_players = sorted(
        {
            entry.player_name
            for session in ordered_sessions
            for entry in session.entries
        },
        key=str.casefold,
    )

    labels = [session_chart_label(session) for session in ordered_sessions]
    datasets = []

    for player_name in all_players:
        running_total = 0
        seen_player = False
        data: list[float | None] = []

        for session in ordered_sessions:
            matching_entry = next(
                (
                    entry
                    for entry in session.entries
                    if entry.player_name == player_name
                ),
                None,
            )

            if matching_entry is None:
                data.append(running_total / 100 if seen_player else None)
                continue

            seen_player = True
            running_total += matching_entry.net_cents
            data.append(round(running_total / 100, 2))

        datasets.append(
            {
                "label": player_name,
                "data": data,
            }
        )

    return {
        "labels": labels,
        "datasets": datasets,
    }


def player_session_series(
    sessions: list[SessionSummary], player_name: str
) -> dict[str, Any]:
    ordered_sessions = sorted(sessions, key=session_sort_key)
    labels: list[str] = []
    net_values: list[float] = []
    cumulative_values: list[float] = []
    running_total = 0

    all_player_names = sorted(
        {
            entry.player_name
            for session in ordered_sessions
            for entry in session.entries
        },
        key=str.casefold,
    )

    for session in ordered_sessions:
        matching_entry = next(
            (entry for entry in session.entries if entry.player_name == player_name),
            None,
        )
        if matching_entry is None:
            continue

        labels.append(session_chart_label(session))
        net_values.append(round(matching_entry.net_cents / 100, 2))
        running_total += matching_entry.net_cents
        cumulative_values.append(round(running_total / 100, 2))

    return {
        "labels": labels,
        "color": color_for_name(player_name, all_player_names),
        "net_values": net_values,
        "net_colors": [net_tone(round(value * 100)) for value in net_values],
        "cumulative_values": cumulative_values,
    }


def session_breakdown_series(session: SessionSummary) -> dict[str, Any]:
    ordered_entries = sorted(
        session.entries,
        key=lambda entry: (entry.net_cents, entry.player_name.casefold()),
        reverse=True,
    )

    return {
        "labels": [entry.player_name for entry in ordered_entries],
        "net_values": [round(entry.net_cents / 100, 2) for entry in ordered_entries],
        "net_colors": [net_tone(entry.net_cents) for entry in ordered_entries],
    }


def session_events(events: list[EventRow], session_id: str) -> list[EventRow]:
    return [event for event in events if event["session_id"] == session_id]


def unique_player_names(events: list[EventRow]) -> list[str]:
    return sorted(
        {event["player_name"] for event in events if event["player_name"].strip()},
        key=str.casefold,
    )
