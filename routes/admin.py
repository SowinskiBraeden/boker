#!/usr/bin/env python3
from __future__ import annotations

import csv
from datetime import datetime, timezone

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session as flask_session,
    url_for,
)

from auth import is_admin
from services import (
    build_session_summaries,
    next_session_id,
    pending_payout_carry_items,
    prunable_empty_session_ids,
    unique_player_names,
)
from storage import CSV_HEADERS, append_event, load_events, write_events
from utils import cents_to_dollars, session_label

admin_bp = Blueprint("admin", __name__)

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


@admin_bp.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if (
            username == current_app.config["ADMIN_USERNAME"]
            and password == current_app.config["ADMIN_PASSWORD"]
        ):
            flask_session.pop("user_id", None)
            flask_session["is_admin"] = True
            flash("Admin login successful.", "success")
            return redirect(url_for("admin.dashboard"))

        flash("Invalid admin credentials.", "error")

    return render_template("admin_login.html")


@admin_bp.post("/admin/logout")
def logout():
    flask_session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("public.home"))


@admin_bp.post("/admin/session-state")
def session_state():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin.login"))

    data_path = current_app.config["DATA_PATH"]
    session_id = request.form.get("session_id", "").strip()
    state = request.form.get("state", "").strip()

    events = load_events(data_path)
    sessions = build_session_summaries(events)
    by_id = {s.session_id: s for s in sessions}
    target = by_id.get(session_id)

    if target is None:
        flash("Session not found.", "error")
        return redirect(url_for("admin.dashboard"))

    if state not in {"open", "closed"}:
        flash("Invalid session state.", "error")
        return redirect(url_for("admin.dashboard"))

    append_event(
        data_path,
        session_id=target.session_id,
        session_date=target.session_date,
        amount_cents=0,
        player_name="",
        event_type="session_open" if state == "open" else "session_close",
        note=f"Session marked {state}.",
        actor=current_app.config["ADMIN_USERNAME"],
    )

    flash(f"Session marked {state}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.get("/admin/export")
@admin_bp.get("/admin/export.csv")
def export_csv():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin.login"))

    data_path = current_app.config["DATA_PATH"]
    export_name = (
        f"entries_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )

    return send_file(
        data_path,
        as_attachment=True,
        download_name=export_name,
        mimetype="text/csv",
    )


@admin_bp.post("/admin/import")
def import_csv():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin.login"))

    data_path = current_app.config["DATA_PATH"]
    uploaded_file = request.files.get("csv_file")
    if uploaded_file is None or uploaded_file.filename == "":
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("admin.dashboard"))

    if not uploaded_file.filename.lower().endswith(".csv"):
        flash("Only CSV files are allowed.", "error")
        return redirect(url_for("admin.dashboard"))

    try:
        uploaded_text = uploaded_file.stream.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("CSV file must be valid UTF-8 text.", "error")
        return redirect(url_for("admin.dashboard"))

    uploaded_lines = uploaded_text.splitlines()
    if not uploaded_lines:
        flash("CSV file is empty.", "error")
        return redirect(url_for("admin.dashboard"))

    try:
        uploaded_header = next(csv.reader(uploaded_lines))
    except Exception:
        flash("Could not read the uploaded CSV header.", "error")
        return redirect(url_for("admin.dashboard"))

    if uploaded_header != CSV_HEADERS:
        flash("CSV header does not match the current audit format.", "error")
        return redirect(url_for("admin.dashboard"))

    try:
        existing_ids = {event["id"] for event in load_events(data_path)}
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
            with open(data_path, "a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
                writer.writerows(new_rows)

        flash(
            f"Imported {len(new_rows)} new events, skipped {skipped_count} duplicates.",
            "success",
        )
    except Exception:
        flash("Import failed. Existing CSV was not updated.", "error")

    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/admin/write-off-front")
def write_off_front():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin.login"))

    data_path = current_app.config["DATA_PATH"]
    debt_key = request.form.get("debt_key", "").strip()
    note = request.form.get("note", "").strip()
    amount_raw = request.form.get("amount", "0").strip()

    try:
        amount_cents = int(round(float(amount_raw) * 100))
    except ValueError:
        flash("Amount must be a number.", "error")
        return redirect(url_for("admin.dashboard"))

    if amount_cents <= 0:
        flash("Write-off amount must be greater than zero.", "error")
        return redirect(url_for("admin.dashboard"))

    try:
        session_id, player_name = debt_key.split("||", 1)
    except ValueError:
        flash("Select a valid player debt.", "error")
        return redirect(url_for("admin.dashboard"))

    events = load_events(data_path)
    sessions = build_session_summaries(events)
    target = next((s for s in sessions if s.session_id == session_id), None)

    if target is None:
        flash("Session not found.", "error")
        return redirect(url_for("admin.dashboard"))

    entry = next(
        (e for e in target.entries if e.player_name == player_name),
        None,
    )

    if entry is None or entry.player_owes_cents <= 0:
        flash("That player does not have an outstanding debt.", "error")
        return redirect(url_for("admin.dashboard"))

    if amount_cents > entry.player_owes_cents:
        flash(
            f"Write-off cannot exceed {cents_to_dollars(entry.player_owes_cents)}.",
            "error",
        )
        return redirect(url_for("admin.dashboard"))

    append_event(
        data_path,
        session_id=target.session_id,
        session_date=target.session_date,
        player_name=entry.player_name,
        event_type="writeoff",
        amount_cents=amount_cents,
        note=note or "Debt written off.",
        actor=current_app.config["ADMIN_USERNAME"],
    )

    flash("Debt written off.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/admin/collect-front")
def collect_front():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin.login"))

    data_path = current_app.config["DATA_PATH"]
    debt_key = request.form.get("debt_key", "").strip()
    note = request.form.get("note", "").strip()
    amount_raw = request.form.get("amount", "0").strip()

    try:
        amount_cents = int(round(float(amount_raw) * 100))
    except ValueError:
        flash("Amount must be a number.", "error")
        return redirect(url_for("admin.dashboard"))

    if amount_cents <= 0:
        flash("Collected amount must be greater than zero.", "error")
        return redirect(url_for("admin.dashboard"))

    try:
        session_id, player_name = debt_key.split("||", 1)
    except ValueError:
        flash("Select a valid player debt.", "error")
        return redirect(url_for("admin.dashboard"))

    events = load_events(data_path)
    sessions = build_session_summaries(events)
    target = next((s for s in sessions if s.session_id == session_id), None)

    if target is None:
        flash("Session not found.", "error")
        return redirect(url_for("admin.dashboard"))

    entry = next(
        (e for e in target.entries if e.player_name == player_name),
        None,
    )

    if entry is None or entry.player_owes_cents <= 0:
        flash("That player does not have an outstanding debt.", "error")
        return redirect(url_for("admin.dashboard"))

    if amount_cents > entry.player_owes_cents:
        flash(
            f"Collection cannot exceed {cents_to_dollars(entry.player_owes_cents)}.",
            "error",
        )
        return redirect(url_for("admin.dashboard"))

    append_event(
        data_path,
        session_id=target.session_id,
        session_date=target.session_date,
        player_name=entry.player_name,
        event_type="debt_repayment",
        amount_cents=amount_cents,
        note=note or "Debt repayment collected.",
        actor=current_app.config["ADMIN_USERNAME"],
    )

    flash("Debt repayment collected.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/admin/open-session")
def open_session():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin.login"))

    data_path = current_app.config["DATA_PATH"]
    session_date = request.form.get("session_date", "").strip()
    if not session_date:
        flash("Session date is required.", "error")
        return redirect(url_for("admin.dashboard"))

    events = load_events(data_path)
    sessions = build_session_summaries(events)
    new_session_id = next_session_id(sessions, session_date)

    append_event(
        data_path,
        session_id=new_session_id,
        session_date=session_date,
        amount_cents=0,
        player_name="",
        event_type="session_open",
        note="Session opened.",
        actor=current_app.config["ADMIN_USERNAME"],
    )

    flash(f"Opened session {new_session_id}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/admin/prune-empty-sessions")
def prune_empty_sessions():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin.login"))

    data_path = current_app.config["DATA_PATH"]
    events = load_events(data_path)
    sessions = build_session_summaries(events)
    prunable_ids = prunable_empty_session_ids(events, sessions)

    if not prunable_ids:
        flash("No empty marker-only sessions to prune.", "success")
        return redirect(url_for("admin.dashboard"))

    pruned_events = [
        event
        for event in events
        if (event["session_id"].strip() or event["session_date"].strip())
        not in prunable_ids
    ]
    write_events(data_path, pruned_events)

    flash(
        f"Pruned {len(prunable_ids)} empty session"
        f"{'s' if len(prunable_ids) != 1 else ''}.",
        "success",
    )
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/admin/apply-payout-carry-in")
def apply_payout_carry_in():
    if not is_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("admin.login"))

    data_path = current_app.config["DATA_PATH"]
    session_id = request.form.get("session_id", "").strip()
    player_name = request.form.get("player_name", "").strip()

    events = load_events(data_path)
    sessions = build_session_summaries(events)
    by_id = {s.session_id: s for s in sessions}
    target = by_id.get(session_id)

    if target is None or target.status != "open":
        flash("Select a valid open session.", "error")
        return redirect(url_for("admin.dashboard"))

    if not any(e.player_name == player_name for e in target.entries):
        flash("Add that player to the open session before applying carry-in.", "error")
        return redirect(url_for("admin.dashboard"))

    pending_by_player = {
        str(item["player_name"]): int(item["amount_cents"])
        for item in pending_payout_carry_items(sessions)
    }
    amount_cents = pending_by_player.get(player_name, 0)

    if amount_cents <= 0:
        flash("No pending payout carry-in found for that player.", "error")
        return redirect(url_for("admin.dashboard"))

    append_event(
        data_path,
        session_id=target.session_id,
        session_date=target.session_date,
        player_name=player_name,
        event_type="payout_carry_in",
        amount_cents=amount_cents,
        note="Payout carry-in from prior carry-out.",
        actor=current_app.config["ADMIN_USERNAME"],
    )

    flash(
        f"Applied {cents_to_dollars(amount_cents)} payout carry-in for {player_name}.",
        "success",
    )
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin", methods=["GET", "POST"])
def dashboard():
    if not is_admin():
        return redirect(url_for("admin.login"))

    data_path = current_app.config["DATA_PATH"]

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
            return redirect(url_for("admin.dashboard"))

        events = load_events(data_path)
        sessions = build_session_summaries(events)
        by_id = {s.session_id: s for s in sessions}
        target = by_id.get(session_id)

        if target is None:
            flash("Select a valid open session.", "error")
            return redirect(url_for("admin.dashboard"))

        if target.status != "open":
            flash(
                "That session is closed. Reopen it first if you need to add events.",
                "error",
            )
            return redirect(url_for("admin.dashboard"))

        append_event(
            data_path,
            session_id=target.session_id,
            session_date=target.session_date,
            player_name=player_name,
            event_type=event_type,
            amount_cents=amount_cents,
            note=note,
            actor=current_app.config["ADMIN_USERNAME"],
        )

        flash("Event added.", "success")
        return redirect(
            url_for(
                "admin.dashboard",
                session_id=session_id,
                player_name=player_name,
                event_type=event_type,
            )
        )

    events = load_events(data_path)
    sessions = build_session_summaries(events)
    empty_session_count = len(prunable_empty_session_ids(events, sessions))
    pending_carry_items = pending_payout_carry_items(sessions)
    pending_carry_total_cents = sum(
        int(item["amount_cents"]) for item in pending_carry_items
    )
    open_sessions = [s for s in sessions if s.status == "open"]
    live_session = open_sessions[0] if open_sessions else None
    live_session_player_names = (
        {e.player_name for e in live_session.entries}
        if live_session is not None
        else set()
    )
    live_session_no = ""
    live_unresolved_count = 0
    if live_session is not None:
        live_session_no = f"#{len(sessions):03d}"
        live_unresolved_count = sum(
            1
            for e in live_session.entries
            if e.current_due_cents > 0 or e.player_owes_cents > 0
        )

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
        {"session": s, "entry": e}
        for s in sessions
        for e in s.entries
        if e.player_owes_cents > 0
    ]

    cash_in_cents = sum(s.total_banker_cash_in_cents for s in sessions)
    cash_out_cents = sum(s.total_banker_cash_out_cents for s in sessions)
    house_owes_players_cents = (
        sum(s.total_current_due_to_player_cents for s in sessions)
        + pending_carry_total_cents
    )
    players_owe_house_cents = sum(
        s.total_current_due_to_house_cents for s in sessions
    )
    admin_totals = {
        "cash_in_cents": cash_in_cents,
        "cash_out_cents": cash_out_cents,
        "house_owes_players_cents": house_owes_players_cents,
        "players_owe_house_cents": players_owe_house_cents,
        "pending_carry_cents": pending_carry_total_cents,
        "collected_cents": sum(s.total_debt_repayment_cents for s in sessions),
        "written_off_cents": sum(s.total_writeoff_cents for s in sessions),
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
        recent_sessions=sessions,
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
