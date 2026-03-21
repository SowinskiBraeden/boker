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
    session_date: str
    player_name: str
    buy_in_cents: int = 0
    cash_out_cents: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def net_cents(self) -> int:
        return self.cash_out_cents - self.buy_in_cents


@dataclass
class SessionSummary:
    session_date: str
    entries: list[SessionEntry]
    status: str = "closed"

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def total_buy_in_cents(self) -> int:
        return sum(entry.buy_in_cents for entry in self.entries)

    @property
    def total_cash_out_cents(self) -> int:
        return sum(entry.cash_out_cents for entry in self.entries)

    @property
    def total_net_cents(self) -> int:
        return sum(entry.net_cents for entry in self.entries)


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
    total_cash_out_cents: int
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


def safe_date_label(session_date: str) -> str:
    try:
        return datetime.strptime(session_date, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return session_date


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
    session_dates_seen: set[str] = set()

    for event in events:
        session_date = event["session_date"]
        event_type = event["event_type"]

        if not session_date:
            continue

        session_dates_seen.add(session_date)

        if event_type == "session_open":
            session_status[session_date] = "open"
            continue

        if event_type == "session_close":
            session_status[session_date] = "closed"
            continue

        player_name = event["player_name"].strip()
        if not player_name:
            continue

        key = (session_date, player_name)
        if key not in grouped:
            grouped[key] = SessionEntry(
                session_date=session_date,
                player_name=player_name,
            )

        entry = grouped[key]

        if event_type == "buyin":
            entry.buy_in_cents += event["amount_cents"]
        elif event_type == "cashout":
            entry.cash_out_cents += event["amount_cents"]

        if event["note"]:
            entry.notes.append(event["note"])

    for entry in grouped.values():
        by_session[entry.session_date].append(entry)

    sessions: list[SessionSummary] = []
    for session_date in session_dates_seen:
        entries = sorted(
            by_session.get(session_date, []),
            key=lambda entry: entry.player_name.casefold(),
        )

        sessions.append(
            SessionSummary(
                session_date=session_date,
                entries=entries,
                status=session_status.get(session_date, "closed"),
            )
        )

    sessions.sort(key=lambda session: session.session_date, reverse=True)
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
        total_buy_in = sum(entry.buy_in_cents for entry in entries)
        total_cash_out = sum(entry.cash_out_cents for entry in entries)
        total_net = total_cash_out - total_buy_in
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
        roi_pct = (total_net / total_buy_in * 100) if total_buy_in else 0.0

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
                total_cash_out_cents=total_cash_out,
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


def cumulative_profit_series(sessions: list[SessionSummary]) -> dict[str, Any]:
    ordered_sessions = sorted(sessions, key=lambda session: session.session_date)
    player_names = sorted(
        {
            entry.player_name
            for session in ordered_sessions
            for entry in session.entries
        },
        key=str.casefold,
    )

    labels = [safe_date_label(session.session_date) for session in ordered_sessions]
    datasets = []

    for player_name in player_names:
        series: list[float | None] = []
        running_total = 0
        has_started = False

        for session in ordered_sessions:
            matching_entry = next(
                (
                    entry
                    for entry in session.entries
                    if entry.player_name == player_name
                ),
                None,
            )
            if matching_entry is not None:
                has_started = True
                running_total += matching_entry.net_cents
                series.append(round(running_total / 100, 2))
            elif has_started:
                series.append(round(running_total / 100, 2))
            else:
                series.append(None)

        datasets.append(
            {
                "label": player_name,
                "data": series,
                "borderColor": color_for_name(player_name, player_names),
                "backgroundColor": color_for_name(player_name, player_names),
                "pointRadius": 3,
                "pointHoverRadius": 5,
                "pointHitRadius": 10,
                "borderWidth": 2.5,
                "tension": 0.22,
                "spanGaps": False,
            }
        )

    return {"labels": labels, "datasets": datasets}


def player_session_series(
    sessions: list[SessionSummary], player_name: str
) -> dict[str, Any]:
    ordered_sessions = sorted(sessions, key=lambda session: session.session_date)
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

        labels.append(safe_date_label(session.session_date))
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


def session_events(events: list[EventRow], session_date: str) -> list[EventRow]:
    return [event for event in events if event["session_date"] == session_date]


def unique_player_names(events: list[EventRow]) -> list[str]:
    return sorted(
        {event["player_name"] for event in events if event["player_name"].strip()},
        key=str.casefold,
    )
