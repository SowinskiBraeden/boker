#!/usr/bin/env python3
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask import current_app

from charts import cumulative_profit_series, player_session_series, session_breakdown_series
from config import ELIGIBLE_MIN_SESSIONS
from services import (
    apply_rank_changes,
    build_leaderboard,
    build_session_summaries,
    session_events,
)
from storage import load_events
from utils import session_label, session_sort_key

public_bp = Blueprint("public", __name__)


@public_bp.get("/")
def home():
    return render_template("landing.html")


@public_bp.get("/help")
def help():
    return render_template("docs.html")


@public_bp.get("/explore")
def explore():
    from auth import is_logged_in
    from db import database_extensions_available
    from league_repositories import league_counts, list_public_leagues

    q = request.args.get("q", "").strip()
    leagues = list_public_leagues(q) if database_extensions_available() else []
    counts = {league.id: league_counts(league.id) for league in leagues}
    return render_template("explore.html", leagues=leagues, counts=counts, q=q)


@public_bp.get("/leaderboard")
def leaderboard():
    events = load_events(current_app.config["DATA_PATH"])
    all_sessions = build_session_summaries(events)
    ordered_sessions = sorted(all_sessions, key=session_sort_key)

    session_ids = [s.session_id for s in ordered_sessions]
    selected_session_id = request.args.get("through_session", "").strip()
    mode = request.args.get("mode", "eligible").strip()
    if mode not in ("eligible", "all", "recent"):
        mode = "eligible"
    label = ""
    cutoff_index = len(session_ids) - 1

    if session_ids:
        if selected_session_id in session_ids:
            cutoff_index = session_ids.index(selected_session_id)
            label = session_label(ordered_sessions[cutoff_index])
        else:
            label = session_label(ordered_sessions[cutoff_index])

        filtered_sessions = ordered_sessions[: cutoff_index + 1]
        previous_sessions = ordered_sessions[:cutoff_index]
    else:
        filtered_sessions = []
        previous_sessions = []

    board = build_leaderboard(filtered_sessions)
    previous_board = build_leaderboard(previous_sessions)
    board = apply_rank_changes(board, previous_board)

    eligible_count = sum(1 for p in board if p.sessions_played >= ELIGIBLE_MIN_SESSIONS)
    all_count = len(board)
    recent_sessions_slice = filtered_sessions[-5:]
    recent_count = len({
        entry.player_name
        for s in recent_sessions_slice
        for entry in s.entries
    })

    if mode == "recent":
        mode_board = build_leaderboard(recent_sessions_slice)
        main_board = mode_board
        provisional_board = []
    elif mode == "eligible":
        main_board = [p for p in board if p.sessions_played >= ELIGIBLE_MIN_SESSIONS]
        provisional_board = [p for p in board if p.sessions_played < ELIGIBLE_MIN_SESSIONS]
    else:
        main_board = board
        provisional_board = []

    chart_data = cumulative_profit_series(filtered_sessions)
    cash_paid_out_cents = sum(s.total_paid_out_cents for s in all_sessions)

    return render_template(
        "leaderboard.html",
        main_board=main_board,
        provisional_board=provisional_board,
        mode=mode,
        eligible_count=eligible_count,
        all_count=all_count,
        recent_count=recent_count,
        eligible_min_sessions=ELIGIBLE_MIN_SESSIONS,
        session_count=len(filtered_sessions),
        total_session_count=len(all_sessions),
        cash_paid_out_cents=cash_paid_out_cents,
        chart_data=chart_data,
        available_sessions=all_sessions,
        selected_session_id=selected_session_id,
        selected_session_label=(label if selected_session_id else "Latest session"),
        selected_session_date=(
            ordered_sessions[cutoff_index].session_date
            if selected_session_id and session_ids
            else ""
        ),
        session_label=session_label,
    )


@public_bp.get("/sessions")
def sessions():
    events = load_events(current_app.config["DATA_PATH"])
    all_sessions = build_session_summaries(events)

    return render_template(
        "sessions.html",
        sessions=all_sessions,
        session_label=session_label,
    )


@public_bp.get("/sessions/<session_id>")
def session_detail(session_id: str):
    events = load_events(current_app.config["DATA_PATH"])
    all_sessions = build_session_summaries(events)
    target_session = next(
        (s for s in all_sessions if s.session_id == session_id),
        None,
    )
    if target_session is None:
        flash("That session was not found.", "error")
        return redirect(url_for("public.sessions"))

    chronological_sessions = sorted(all_sessions, key=session_sort_key)
    chronological_index = next(
        index
        for index, s in enumerate(chronological_sessions)
        if s.session_id == session_id
    )
    target_session = chronological_sessions[chronological_index]
    session_number = chronological_index + 1
    prev_session = (
        chronological_sessions[chronological_index - 1]
        if chronological_index > 0
        else None
    )
    next_session = (
        chronological_sessions[chronological_index + 1]
        if chronological_index < len(chronological_sessions) - 1
        else None
    )

    return render_template(
        "session_detail.html",
        session=target_session,
        next_session=next_session,
        prev_session=prev_session,
        session_number=session_number,
        raw_events=session_events(events, session_id),
        chart_data=session_breakdown_series(target_session),
        session_label=session_label,
    )


@public_bp.get("/players/<player_name>")
def player_detail(player_name: str):
    events = load_events(current_app.config["DATA_PATH"])
    all_sessions = build_session_summaries(events)
    board = build_leaderboard(all_sessions)
    player_stats = next(
        (player for player in board if player.player_name == player_name), None
    )
    if player_stats is None:
        flash("That player was not found.", "error")
        return redirect(url_for("public.leaderboard"))

    player_rank = next(
        (
            index
            for index, ranked_player in enumerate(board, start=1)
            if ranked_player.player_name == player_name
        ),
        None,
    )
    chart_data = player_session_series(all_sessions, player_name)
    return render_template(
        "player_detail.html",
        player=player_stats,
        player_rank=player_rank,
        chart_data=chart_data,
    )
