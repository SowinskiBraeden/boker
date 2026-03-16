#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for

from stats import (
    build_leaderboard,
    build_session_summaries,
    cents_to_dollars,
    cumulative_profit_series,
    player_session_series,
    safe_date_label,
    session_events,
    unique_player_names,
)
from storage import append_event, ensure_data_file, load_events

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "entries.csv"
ENV_PATH = BASE_DIR / ".env"


def load_local_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_local_env(ENV_PATH)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-before-deploying")
app.config["ADMIN_USERNAME"] = os.getenv("ADMIN_USERNAME", "admin")
app.config["ADMIN_PASSWORD"] = os.getenv("ADMIN_PASSWORD", "change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_NAME"] = "poker_portal_session"

ensure_data_file(DATA_PATH)
app.jinja_env.filters["money"] = cents_to_dollars
app.jinja_env.filters["pretty_date"] = safe_date_label


def is_admin() -> bool:
    return bool(session.get("is_admin"))


@app.context_processor
def inject_globals() -> dict[str, object]:
    return {"is_admin": is_admin()}


@app.get("/")
def home() -> str:
    return redirect(url_for("leaderboard"))


@app.get("/leaderboard")
def leaderboard() -> str:
    events = load_events(DATA_PATH)
    all_sessions = build_session_summaries(events)
    selected_session_date = request.args.get("through_session", "").strip()
    valid_session_dates = {session.session_date for session in all_sessions}

    if selected_session_date not in valid_session_dates:
        selected_session_date = ""

    filtered_sessions = all_sessions
    if selected_session_date:
        filtered_sessions = [
            session
            for session in all_sessions
            if session.session_date <= selected_session_date
        ]

    board = build_leaderboard(filtered_sessions)
    chart_data = cumulative_profit_series(filtered_sessions)
    return render_template(
        "leaderboard.html",
        leaderboard=board,
        session_count=len(filtered_sessions),
        total_session_count=len(all_sessions),
        chart_data=chart_data,
        available_sessions=all_sessions,
        selected_session_date=selected_session_date,
        selected_session_label=(
            safe_date_label(selected_session_date)
            if selected_session_date
            else "Latest session"
        ),
    )


@app.get("/sessions")
def sessions() -> str:
    events = load_events(DATA_PATH)
    session_summaries = build_session_summaries(events)
    return render_template("sessions.html", sessions=session_summaries)


@app.get("/sessions/<session_date>")
def session_detail(session_date: str) -> str:
    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    target_session = next(
        (
            session_summary
            for session_summary in sessions
            if session_summary.session_date == session_date
        ),
        None,
    )
    if target_session is None:
        flash("That session was not found.", "error")
        return redirect(url_for("sessions"))

    return render_template(
        "session_detail.html",
        session=target_session,
        raw_events=session_events(events, session_date),
    )


@app.get("/players/<player_name>")
def player_detail(player_name: str) -> str:
    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    board = build_leaderboard(sessions)
    player_stats = next(
        (player for player in board if player.player_name == player_name), None
    )
    if player_stats is None:
        flash("That player was not found.", "error")
        return redirect(url_for("leaderboard"))

    chart_data = player_session_series(sessions, player_name)
    return render_template(
        "player_detail.html",
        player=player_stats,
        chart_data=chart_data,
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login() -> str:
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if (
            username == app.config["ADMIN_USERNAME"]
            and password == app.config["ADMIN_PASSWORD"]
        ):
            session["is_admin"] = True
            flash("Admin login successful.", "success")
            return redirect(url_for("admin_dashboard"))

        flash("Invalid admin credentials.", "error")

    return render_template("admin_login.html")


@app.post("/admin/logout")
def admin_logout() -> str:
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("leaderboard"))


@app.route("/admin", methods=["GET", "POST"])
def admin_dashboard() -> str:
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        session_date = request.form.get("session_date", "").strip()
        player_name = request.form.get("player_name", "").strip()
        event_type = request.form.get("event_type", "").strip()
        amount_raw = request.form.get("amount", "0").strip()
        note = request.form.get("note", "").strip()

        if not session_date or not player_name or not event_type:
            flash("Session date, player name, and event type are required.", "error")
            return redirect(url_for("admin_dashboard"))

        try:
            amount_cents = 0 if event_type == "note" else round(float(amount_raw) * 100)
        except ValueError:
            flash("Amount must be a valid number.", "error")
            return redirect(url_for("admin_dashboard"))

        append_event(
            DATA_PATH,
            session_date=session_date,
            player_name=player_name,
            event_type=event_type,
            amount_cents=amount_cents,
            note=note,
            actor=app.config["ADMIN_USERNAME"],
        )
        flash("Event added to the ledger.", "success")
        return redirect(url_for("admin_dashboard"))

    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    recent_sessions = sessions[:6]
    recent_events = list(reversed(events[-20:]))
    return render_template(
        "admin_dashboard.html",
        recent_sessions=recent_sessions,
        recent_events=recent_events,
        player_names=unique_player_names(events),
    )


if __name__ == "__main__":
    app.run(debug=True)
