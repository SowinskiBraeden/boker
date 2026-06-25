#!/usr/bin/env python3
"""Domain logic: session building, leaderboard, and ledger helpers."""
from __future__ import annotations

from collections import defaultdict

from .models import PlayerStats, SessionEntry, SessionSummary
from .storage import EventRow
from .utils import entry_sort_key, net_result_bucket, session_sort_key

SESSION_MARKER_TYPES = {"session_open", "session_close"}


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
        elif event_type == "front_collected":
            entry.front_collected_cents += event["amount_cents"]
        elif event_type == "debt_repayment":
            entry.front_collected_cents += event["amount_cents"]
        elif event_type == "front_writeoff":
            entry.front_writeoff_cents += event["amount_cents"]
        elif event_type == "writeoff":
            entry.front_writeoff_cents += event["amount_cents"]
        elif event_type == "rollover_in":
            entry.rollover_in_cents += event["amount_cents"]
        elif event_type == "payout_carry_in":
            entry.payout_carry_in_cents += event["amount_cents"]
        elif event_type == "cashout":
            entry.cash_out_cents += event["amount_cents"]
        elif event_type == "paid":
            entry.paid_cents += event["amount_cents"]
        elif event_type == "paid_out":
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

    sessions.sort(key=session_sort_key, reverse=True)
    return sessions


def summarize_player_runs(entries: list[SessionEntry]) -> dict[str, int | str | None]:
    ordered_entries = sorted(entries, key=entry_sort_key)

    longest_win_streak = 0
    longest_loss_streak = 0
    current_run_wins = 0
    current_run_losses = 0

    best_entry: SessionEntry | None = None
    worst_entry: SessionEntry | None = None

    for entry in ordered_entries:
        net = entry.net_cents
        bucket = net_result_bucket(net)

        if best_entry is None or net > best_entry.net_cents:
            best_entry = entry

        if worst_entry is None or net < worst_entry.net_cents:
            worst_entry = entry

        if bucket == "win":
            current_run_wins += 1
            current_run_losses = 0
        elif bucket == "loss":
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
        bucket = net_result_bucket(entry.net_cents)

        if bucket == "win":
            if current_loss_streak > 0:
                break
            current_win_streak += 1
        elif bucket == "loss":
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
        wins = [value for value in nets if net_result_bucket(value) == "win"]
        losses = [value for value in nets if net_result_bucket(value) == "loss"]

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
        total_front_collected = sum(entry.debt_repayment_cents for entry in entries)
        total_front_writeoff = sum(entry.writeoff_cents for entry in entries)
        current_player_owes = sum(entry.player_owes_cents for entry in entries)
        total_rollover_in = sum(entry.rollover_in_cents for entry in entries)
        total_payout_carry_in = sum(entry.payout_carry_in_cents for entry in entries)
        total_invested = sum(entry.invested_cents for entry in entries)
        total_cash_out = sum(entry.cash_out_cents for entry in entries)
        total_gross_payout = sum(entry.gross_payout_cents for entry in entries)
        total_paid = sum(entry.paid_out_cents for entry in entries)
        total_rollover_out = sum(entry.rollover_out_cents for entry in entries)
        current_due_to_player = sum(entry.current_due_to_player_cents for entry in entries)
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
                total_front_collected_cents=total_front_collected,
                total_front_writeoff_cents=total_front_writeoff,
                current_player_owes_cents=current_player_owes,
                total_rollover_in_cents=total_rollover_in,
                total_payout_carry_in_cents=total_payout_carry_in,
                total_invested_cents=total_invested,
                total_cash_out_cents=total_cash_out,
                total_gross_payout_cents=total_gross_payout,
                total_paid_cents=total_paid,
                total_rollover_out_cents=total_rollover_out,
                current_due_to_player_cents=current_due_to_player,
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


def next_session_id(sessions: list[SessionSummary], session_date: str) -> str:
    matching = [s for s in sessions if s.session_date == session_date]

    highest = 0
    for s in matching:
        if s.session_id == session_date:
            highest = max(highest, 1)
            continue

        suffix = s.session_id.replace(f"{session_date}-", "")
        if suffix.isdigit():
            highest = max(highest, int(suffix))

    return f"{session_date}-{highest + 1:02d}"


def prunable_empty_session_ids(
    events: list[EventRow], sessions: list[SessionSummary]
) -> set[str]:
    empty_session_ids = {s.session_id for s in sessions if len(s.entries) == 0}
    session_event_map: dict[str, list[EventRow]] = {}

    for event in events:
        session_id = event["session_id"].strip() or event["session_date"].strip()
        if session_id in empty_session_ids:
            session_event_map.setdefault(session_id, []).append(event)

    return {
        session_id
        for session_id, rows in session_event_map.items()
        if rows
        and all(
            row["event_type"] in SESSION_MARKER_TYPES
            and not row["player_name"].strip()
            and row["amount_cents"] == 0
            for row in rows
        )
    }


def pending_payout_carry_items(sessions: list[SessionSummary]) -> list[dict[str, object]]:
    carried_out: dict[str, int] = {}
    carried_in: dict[str, int] = {}

    for session_summary in sessions:
        for entry in session_summary.entries:
            carried_out[entry.player_name] = (
                carried_out.get(entry.player_name, 0) + entry.rollover_out_cents
            )
            carried_in[entry.player_name] = (
                carried_in.get(entry.player_name, 0)
                + entry.rollover_in_cents
                + entry.payout_carry_in_cents
            )

    items = []
    for player_name, amount_out in carried_out.items():
        pending_cents = amount_out - carried_in.get(player_name, 0)
        if pending_cents > 0:
            items.append({"player_name": player_name, "amount_cents": pending_cents})

    return sorted(items, key=lambda item: str(item["player_name"]).casefold())


def session_events(events: list[EventRow], session_id: str) -> list[EventRow]:
    return [event for event in events if event["session_id"] == session_id]


def unique_player_names(events: list[EventRow]) -> list[str]:
    return sorted(
        {event["player_name"] for event in events if event["player_name"].strip()},
        key=str.casefold,
    )
