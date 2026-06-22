#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
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
    session_label,
    session_sort_key,
    unique_player_names,
)
from storage import (
    CSV_HEADERS,
    EventRow,
    append_event,
    ensure_data_file,
    load_events,
    write_events,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "entries.csv"
ENV_PATH = BASE_DIR / ".env"

ELIGIBLE_MIN_SESSIONS = 3
ADMIN_EVENT_TYPES = [
    ("buyin", "Buy-in", "var(--accent)"),
    ("front", "Front", "var(--warn)"),
    ("rollover_in", "Rollover-in", "var(--rolled)"),
    ("payout_carry_in", "Payout carry-in", "var(--rolled)"),
    ("cashout", "Cashout result", "var(--rank-2)"),
    ("paid_out", "Paid out cash", "var(--pos)"),
    ("rollover_out", "Rollover-out", "var(--rolled)"),
    ("note", "Note", "var(--muted)"),
]
SESSION_MARKER_TYPES = {"session_open", "session_close"}


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


def next_session_id(sessions, session_date: str) -> str:
    matching = [session for session in sessions if session.session_date == session_date]

    highest = 0
    for s in matching:
        if s.session_id == session_date:
            highest = max(highest, 1)
            continue

        suffix = s.session_id.replace(f"{session_date}-", "")
        if suffix.isdigit():
            highest = max(highest, int(suffix))

    return f"{session_date}-{highest + 1:02d}"


def prunable_empty_session_ids(events: list[EventRow], sessions) -> set[str]:
    empty_session_ids = {
        session.session_id for session in sessions if len(session.entries) == 0
    }
    session_events: dict[str, list[EventRow]] = {}

    for event in events:
        session_id = event["session_id"].strip() or event["session_date"].strip()
        if session_id in empty_session_ids:
            session_events.setdefault(session_id, []).append(event)

    return {
        session_id
        for session_id, rows in session_events.items()
        if rows
        and all(
            row["event_type"] in SESSION_MARKER_TYPES
            and not row["player_name"].strip()
            and row["amount_cents"] == 0
            for row in rows
        )
    }


def pending_payout_carry_items(sessions) -> list[dict[str, object]]:
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

    # Build full board (all filtered sessions) for rank changes and counts
    board = build_leaderboard(filtered_sessions)
    previous_board = build_leaderboard(previous_sessions)
    board = apply_rank_changes(board, previous_board)

    # Segmented-control counts
    eligible_count = sum(1 for p in board if p.sessions_played >= ELIGIBLE_MIN_SESSIONS)
    all_count = len(board)
    recent_sessions_slice = filtered_sessions[-5:]
    recent_count = len({
        entry.player_name
        for s in recent_sessions_slice
        for entry in s.entries
    })

    # Mode-specific boards
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
    cash_paid_out_cents = sum(session.total_paid_out_cents for session in all_sessions)

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


@app.get("/sessions")
def sessions():
    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)

    return render_template(
        "sessions.html",
        sessions=sessions,
        session_label=session_label,
    )


@app.get("/sessions/<session_id>")
def session_detail(session_id: str) -> str:
    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    target_session = next(
        (
            session_summary
            for session_summary in sessions
            if session_summary.session_id == session_id
        ),
        None,
    )
    if target_session is None:
        flash("That session was not found.", "error")
        return redirect(url_for("sessions"))

    chronological_sessions = sorted(sessions, key=session_sort_key)
    chronological_index = next(
        index
        for index, session in enumerate(chronological_sessions)
        if session.session_id == session_id
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

    player_rank = next(
        (
            index
            for index, ranked_player in enumerate(board, start=1)
            if ranked_player.player_name == player_name
        ),
        None,
    )
    chart_data = player_session_series(sessions, player_name)
    return render_template(
        "player_detail.html",
        player=player_stats,
        player_rank=player_rank,
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

    session_id = request.form.get("session_id", "").strip()
    state = request.form.get("state", "").strip()

    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    by_id = {session.session_id: session for session in sessions}
    target = by_id.get(session_id)

    if target is None:
        flash("Session not found.", "error")
        return redirect(url_for("admin_dashboard"))

    if state not in {"open", "closed"}:
        flash("Invalid session state.", "error")
        return redirect(url_for("admin_dashboard"))

    append_event(
        DATA_PATH,
        session_id=target.session_id,
        session_date=target.session_date,
        amount_cents=0,
        player_name="",
        event_type="session_open" if state == "open" else "session_close",
        note=f"Session marked {state}.",
        actor=app.config["ADMIN_USERNAME"],
    )

    flash(f"Session marked {state}.", "success")
    return redirect(url_for("admin_dashboard"))


@app.get("/admin/export")
@app.get("/admin/export.csv")
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
        uploaded_header = next(csv.reader(uploaded_lines))
    except Exception:
        flash("Could not read the uploaded CSV header.", "error")
        return redirect(url_for("admin_dashboard"))

    if uploaded_header != CSV_HEADERS:
        flash("CSV header does not match the current audit format.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        existing_ids = {event["id"] for event in load_events(DATA_PATH)}
        reader = csv.DictReader(uploaded_lines)
        new_rows = []
        skipped_count = 0
        for row in reader:
            event_id = row.get("id", "")
            if not event_id or event_id in existing_ids:
                skipped_count += 1
                continue

            new_rows.append({header: row.get(header, "") for header in CSV_HEADERS})
            existing_ids.add(event_id)

        if new_rows:
            with open(DATA_PATH, "a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
                writer.writerows(new_rows)

        flash(
            f"Imported {len(new_rows)} new events, skipped {skipped_count} duplicates.",
            "success",
        )
    except Exception:
        flash("Import failed. Existing CSV was not updated.", "error")

    return redirect(url_for("admin_dashboard"))


@app.post("/admin/write-off-front")
def admin_write_off_front() -> str:
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))

    debt_key = request.form.get("debt_key", "").strip()
    note = request.form.get("note", "").strip()
    amount_raw = request.form.get("amount", "0").strip()

    try:
        amount_cents = int(round(float(amount_raw) * 100))
    except ValueError:
        flash("Amount must be a number.", "error")
        return redirect(url_for("admin_dashboard"))

    if amount_cents <= 0:
        flash("Write-off amount must be greater than zero.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        session_id, player_name = debt_key.split("||", 1)
    except ValueError:
        flash("Select a valid player debt.", "error")
        return redirect(url_for("admin_dashboard"))

    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    target = next(
        (session for session in sessions if session.session_id == session_id),
        None,
    )

    if target is None:
        flash("Session not found.", "error")
        return redirect(url_for("admin_dashboard"))

    entry = next(
        (entry for entry in target.entries if entry.player_name == player_name),
        None,
    )

    if entry is None or entry.player_owes_cents <= 0:
        flash("That player does not have an outstanding debt.", "error")
        return redirect(url_for("admin_dashboard"))

    if amount_cents > entry.player_owes_cents:
        flash(
            f"Write-off cannot exceed {cents_to_dollars(entry.player_owes_cents)}.",
            "error",
        )
        return redirect(url_for("admin_dashboard"))

    append_event(
        DATA_PATH,
        session_id=target.session_id,
        session_date=target.session_date,
        player_name=entry.player_name,
        event_type="writeoff",
        amount_cents=amount_cents,
        note=note or "Debt written off.",
        actor=app.config["ADMIN_USERNAME"],
    )

    flash("Debt written off.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/collect-front")
def admin_collect_front() -> str:
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))

    debt_key = request.form.get("debt_key", "").strip()
    note = request.form.get("note", "").strip()
    amount_raw = request.form.get("amount", "0").strip()

    try:
        amount_cents = int(round(float(amount_raw) * 100))
    except ValueError:
        flash("Amount must be a number.", "error")
        return redirect(url_for("admin_dashboard"))

    if amount_cents <= 0:
        flash("Collected amount must be greater than zero.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        session_id, player_name = debt_key.split("||", 1)
    except ValueError:
        flash("Select a valid player debt.", "error")
        return redirect(url_for("admin_dashboard"))

    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    target = next(
        (session for session in sessions if session.session_id == session_id),
        None,
    )

    if target is None:
        flash("Session not found.", "error")
        return redirect(url_for("admin_dashboard"))

    entry = next(
        (entry for entry in target.entries if entry.player_name == player_name),
        None,
    )

    if entry is None or entry.player_owes_cents <= 0:
        flash("That player does not have an outstanding debt.", "error")
        return redirect(url_for("admin_dashboard"))

    if amount_cents > entry.player_owes_cents:
        flash(
            f"Collection cannot exceed {cents_to_dollars(entry.player_owes_cents)}.",
            "error",
        )
        return redirect(url_for("admin_dashboard"))

    append_event(
        DATA_PATH,
        session_id=target.session_id,
        session_date=target.session_date,
        player_name=entry.player_name,
        event_type="debt_repayment",
        amount_cents=amount_cents,
        note=note or "Debt repayment collected.",
        actor=app.config["ADMIN_USERNAME"],
    )

    flash("Debt repayment collected.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/open-session")
def admin_open_session() -> str:
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))

    session_date = request.form.get("session_date", "").strip()
    if not session_date:
        flash("Session date is required.", "error")
        return redirect(url_for("admin_dashboard"))

    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    session_id = next_session_id(sessions, session_date)

    append_event(
        DATA_PATH,
        session_id=session_id,
        session_date=session_date,
        amount_cents=0,
        player_name="",
        event_type="session_open",
        note="Session opened.",
        actor=app.config["ADMIN_USERNAME"],
    )

    flash(f"Opened session {session_id}.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/prune-empty-sessions")
def admin_prune_empty_sessions() -> str:
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))

    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    prunable_session_ids = prunable_empty_session_ids(events, sessions)

    if not prunable_session_ids:
        flash("No empty marker-only sessions to prune.", "success")
        return redirect(url_for("admin_dashboard"))

    pruned_events = [
        event
        for event in events
        if (event["session_id"].strip() or event["session_date"].strip())
        not in prunable_session_ids
    ]
    write_events(DATA_PATH, pruned_events)

    flash(
        f"Pruned {len(prunable_session_ids)} empty session"
        f"{'s' if len(prunable_session_ids) != 1 else ''}.",
        "success",
    )
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/apply-payout-carry-in")
def admin_apply_payout_carry_in() -> str:
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))

    session_id = request.form.get("session_id", "").strip()
    player_name = request.form.get("player_name", "").strip()

    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    by_id = {session.session_id: session for session in sessions}
    target = by_id.get(session_id)

    if target is None or target.status != "open":
        flash("Select a valid open session.", "error")
        return redirect(url_for("admin_dashboard"))

    if not any(entry.player_name == player_name for entry in target.entries):
        flash("Add that player to the open session before applying carry-in.", "error")
        return redirect(url_for("admin_dashboard"))

    pending_by_player = {
        str(item["player_name"]): int(item["amount_cents"])
        for item in pending_payout_carry_items(sessions)
    }
    amount_cents = pending_by_player.get(player_name, 0)

    if amount_cents <= 0:
        flash("No pending payout carry-in found for that player.", "error")
        return redirect(url_for("admin_dashboard"))

    append_event(
        DATA_PATH,
        session_id=target.session_id,
        session_date=target.session_date,
        player_name=player_name,
        event_type="payout_carry_in",
        amount_cents=amount_cents,
        note="Payout carry-in from prior carry-out.",
        actor=app.config["ADMIN_USERNAME"],
    )

    flash(
        f"Applied {cents_to_dollars(amount_cents)} payout carry-in for {player_name}.",
        "success",
    )
    return redirect(url_for("admin_dashboard"))


@app.route("/admin", methods=["GET", "POST"])
def admin_dashboard():
    if not is_admin():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        session_id = request.form.get("session_id", "").strip()
        player_name = request.form.get("player_name", "").strip()
        event_type = request.form.get("event_type", "").strip()
        note = request.form.get("note", "").strip()

        amount_raw = request.form.get("amount", "0").strip()
        try:
            amount_cents = int(round(float(amount_raw) * 100))
        except ValueError:
            flash("Amount must be a number.", "error")
            return redirect(url_for("admin_dashboard"))

        events = load_events(DATA_PATH)
        sessions = build_session_summaries(events)
        by_id = {session.session_id: session for session in sessions}
        target = by_id.get(session_id)

        if target is None:
            flash("Select a valid open session.", "error")
            return redirect(url_for("admin_dashboard"))

        if target.status != "open":
            flash(
                "That session is closed. Reopen it first if you need to add events.",
                "error",
            )
            return redirect(url_for("admin_dashboard"))

        append_event(
            DATA_PATH,
            session_id=target.session_id,
            session_date=target.session_date,
            player_name=player_name,
            event_type=event_type,
            amount_cents=amount_cents,
            note=note,
            actor=app.config["ADMIN_USERNAME"],
        )

        flash("Event added.", "success")
        return redirect(
            url_for(
                "admin_dashboard",
                session_id=session_id,
                player_name=player_name,
                event_type=event_type,
            )
        )

    events = load_events(DATA_PATH)
    sessions = build_session_summaries(events)
    empty_session_count = len(prunable_empty_session_ids(events, sessions))
    pending_carry_items = pending_payout_carry_items(sessions)
    pending_carry_total_cents = sum(
        int(item["amount_cents"]) for item in pending_carry_items
    )
    open_sessions = [session for session in sessions if session.status == "open"]
    live_session = open_sessions[0] if open_sessions else None
    live_session_player_names = (
        {entry.player_name for entry in live_session.entries}
        if live_session is not None
        else set()
    )
    live_session_no = ""
    live_unresolved_count = 0
    if live_session is not None:
        live_session_no = f"#{len(sessions):03d}"
        live_unresolved_count = sum(
            1
            for entry in live_session.entries
            if entry.current_due_cents > 0 or entry.player_owes_cents > 0
        )

    recent_sessions = sessions
    recent_events = list(reversed(events[-20:]))
    event_type_colors = {value: color for value, _label, color in ADMIN_EVENT_TYPES}
    event_type_labels = {value: label for value, label, _color in ADMIN_EVENT_TYPES}
    selected_event_type = request.args.get("event_type", "buyin").strip()
    if selected_event_type not in event_type_colors:
        selected_event_type = "buyin"
    append_form = {
        "session_id": request.args.get("session_id", "").strip(),
        "player_name": request.args.get("player_name", "").strip(),
        "event_type": selected_event_type,
    }
    debt_entries = [
        {"session": session, "entry": entry}
        for session in sessions
        for entry in session.entries
        if entry.player_owes_cents > 0
    ]

    cash_in_cents = sum(session.total_banker_cash_in_cents for session in sessions)
    cash_out_cents = sum(session.total_banker_cash_out_cents for session in sessions)
    house_owes_players_cents = (
        sum(session.total_current_due_to_player_cents for session in sessions)
        + pending_carry_total_cents
    )
    players_owe_house_cents = sum(
        session.total_current_due_to_house_cents for session in sessions
    )
    admin_totals = {
        "cash_in_cents": cash_in_cents,
        "cash_out_cents": cash_out_cents,
        "house_owes_players_cents": house_owes_players_cents,
        "players_owe_house_cents": players_owe_house_cents,
        "pending_carry_cents": pending_carry_total_cents,
        "collected_cents": sum(
            session.total_debt_repayment_cents for session in sessions
        ),
        "written_off_cents": sum(
            session.total_writeoff_cents for session in sessions
        ),
        "net_book_position_cents": (
            cash_in_cents
            - cash_out_cents
            + players_owe_house_cents
            - house_owes_players_cents
        ),
    }

    return render_template(
        "admin_dashboard.html",
        open_sessions=open_sessions,
        recent_sessions=recent_sessions,
        recent_events=recent_events,
        debt_entries=debt_entries,
        live_session=live_session,
        live_session_player_names=live_session_player_names,
        live_session_no=live_session_no,
        live_unresolved_count=live_unresolved_count,
        pending_carry_items=pending_carry_items,
        player_names=unique_player_names(events),
        append_form=append_form,
        event_types=ADMIN_EVENT_TYPES,
        event_type_colors=event_type_colors,
        event_type_labels=event_type_labels,
        admin_today=datetime.now().date().isoformat(),
        session_label=session_label,
        admin_totals=admin_totals,
        empty_session_count=empty_session_count,
    )


if __name__ == "__main__":
    app.run(debug=True)
