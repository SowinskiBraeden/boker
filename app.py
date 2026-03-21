#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from stats import (
    apply_rank_changes,
    build_leaderboard,
    build_session_summaries,
    cents_to_dollars,
    cumulative_profit_series,
    player_session_series,
    safe_date_label,
    session_breakdown_series,
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
    ordered_sessions = sorted(all_sessions, key=lambda s: s.session_date)

    session_dates = [session.session_date for session in ordered_sessions]
    selected_session_date = request.args.get("through_session", "").strip()

    if session_dates:
        if selected_session_date in session_dates:
            cutoff_index = session_dates.index(selected_session_date)
        else:
            cutoff_index = len(session_dates) - 1
            selected_session = session_dates[cutoff_index]

        filtered_sessions = ordered_sessions[: cutoff_index + 1]
        previous_sessions = ordered_sessions[:cutoff_index]
    else:
        filtered_sessions = []
        previous_sessions = []

    board = build_leaderboard(filtered_sessions)
    previous_board = build_leaderboard(previous_sessions)
    board = apply_rank_changes(board, previous_board)

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

    # sessions are in reverse order
    idx = sessions.index(target_session)
    next_session_idx = idx - 1
    prev_session_idx = idx + 1

    next_session = None
    prev_session = None

    if next_session_idx >= 0:
        next_session = sessions[next_session_idx]

    if prev_session_idx < len(sessions):
        prev_session = sessions[prev_session_idx]

    return render_template(
        "session_detail.html",
        session=target_session,
        next_session=next_session,
        prev_session=prev_session,
        raw_events=session_events(events, session_date),
        chart_data=session_breakdown_series(target_session),
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


@app.post("/admin/session-state")
def admin_session_state() -> str:
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))

    session_date = request.form.get("session_date", "").strip()
    state = request.form.get("state", "").strip()

    if not session_date:
        flash("Session date is required.", "error")
        return redirect(url_for("admin_dashboard"))

    if state not in {"open", "closed"}:
        flash("Invalid session state.", "error")
        return redirect(url_for("admin_dashboard"))

    append_event(
        DATA_PATH,
        session_date=session_date,
        player_name="",
        event_type="session_open" if state == "open" else "session_close",
        amount_cents=0,
        note=f"Session marked {state}.",
        actor=app.config["ADMIN_USERNAME"],
    )
    flash(f"Session marked {state}.", "success")
    return redirect(url_for("admin_dashboard"))


@app.get("/admin/export")
def admin_export_csv():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))

    export_name = (
        f"entries_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )

    return send_file(
        DATA_PATH,
        as_attachment=True,
        download_name=export_name,
        mimetype="text/csv",
    )


@app.post("/admin/import")
def admin_import_csv():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))

    uploaded_file = request.files.get("csv_file")
    if uploaded_file is None or uploaded_file.filename == "":
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("admin_dashboard"))

    if not uploaded_file.filename.lower().endswith(".csv"):
        flash("Only CSV files are allowed.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        uploaded_text = uploaded_file.stream.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("CSV file must be valid UTF-8 text.", "error")
        return redirect(url_for("admin_dashboard"))

    uploaded_lines = uploaded_text.splitlines()
    if not uploaded_lines:
        flash("CSV file is empty.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        current_header = next(
            csv.reader(open(DATA_PATH, "r", encoding="utf-8", newline=""))
        )
    except Exception:
        flash("Could not read the current audit CSV header.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        uploaded_header = next(csv.reader(uploaded_lines))
    except Exception:
        flash("Could not read the uploaded CSV header.", "error")
        return redirect(url_for("admin_dashboard"))

    if uploaded_header != current_header:
        flash("CSV header does not match the current audit format.", "error")
        return redirect(url_for("admin_dashboard"))

    data_dir = os.path.dirname(DATA_PATH)
    backup_name = (
        f"entries_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )
    backup_path = os.path.join(data_dir, backup_name)

    try:
        shutil.copy2(DATA_PATH, backup_path)

        with open(DATA_PATH, "w", encoding="utf-8", newline="") as handle:
            handle.write(uploaded_text)

        flash(f"CSV imported successfully. Backup created: {backup_name}", "success")
    except Exception:
        flash("Import failed. Existing CSV was not updated.", "error")

    return redirect(url_for("admin_dashboard"))


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

        events = load_events(DATA_PATH)
        sessions = build_session_summaries(events)
        status_by_date = {session.session_date: session.status for session in sessions}

        if status_by_date.get(session_date, "closed") != "open":
            flash(
                "That session is closed. Open it first before adding player events.",
                "error",
            )
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
    open_sessions = [session for session in sessions if session.status == "open"]
    recent_events = list(reversed(events[-8:]))

    return render_template(
        "admin_dashboard.html",
        recent_sessions=recent_sessions,
        open_sessions=open_sessions,
        recent_events=recent_events,
        player_names=unique_player_names(events),
    )


if __name__ == "__main__":
    app.run(debug=True)
