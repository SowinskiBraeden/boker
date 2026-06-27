#!/usr/bin/env python3
"""Chart data series builders for the frontend."""
from __future__ import annotations

from typing import Any

from models import SessionEntry, SessionSummary
from utils import net_result_bucket, session_chart_label, session_sort_key

PLAYER_PALETTE = [
    "#9b8cf0",  # --line-1 violet
    "#6fc093",  # --line-2 green
    "#e0b15c",  # --line-3 gold
    "#cf6f86",  # --line-4 pink
    "#8f93c2",  # --line-5 lavender
    "#7cb9e0",
    "#f4a261",
    "#a78bb0",
    "#5cb8a0",
    "#e58f3a",
    "#84cc16",
    "#06b6d4",
]


def color_for_name(name: str, names: list[str]) -> str:
    try:
        index = sorted(names, key=str.casefold).index(name)
    except ValueError:
        index = abs(hash(name))
    return PLAYER_PALETTE[index % len(PLAYER_PALETTE)]


def net_tone(value_cents: int, break_even_cents: int = 100) -> str:
    bucket = net_result_bucket(value_cents, break_even_cents)

    if bucket == "win":
        return "#6fc093"  # --pos
    if bucket == "loss":
        return "#e0758a"  # --neg
    return "#84828e"      # --muted-2


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
        sessions_played = 0
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
            sessions_played += 1
            running_total += matching_entry.net_cents
            data.append(round(running_total / 100, 2))

        datasets.append(
            {
                "label": player_name,
                "data": data,
                "sessions_played": sessions_played,
            }
        )

    return {
        "labels": labels,
        "datasets": datasets,
    }


def player_session_series(
    sessions: list[SessionSummary], player_name: str, break_even_cents: int = 100
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
        "net_colors": [net_tone(round(value * 100), break_even_cents) for value in net_values],
        "cumulative_values": cumulative_values,
    }


def session_breakdown_series(session: SessionSummary, break_even_cents: int = 100) -> dict[str, Any]:
    ordered_entries = sorted(
        session.entries,
        key=lambda entry: (entry.net_cents, entry.player_name.casefold()),
        reverse=True,
    )

    return {
        "labels": [entry.player_name for entry in ordered_entries],
        "net_values": [round(entry.net_cents / 100, 2) for entry in ordered_entries],
        "net_colors": [net_tone(entry.net_cents, break_even_cents) for entry in ordered_entries],
    }
