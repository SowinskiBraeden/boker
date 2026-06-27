#!/usr/bin/env python3
from __future__ import annotations

from datetime import date

import csv
import io
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, url_for

from auth import current_user_id, login_required, normalize_email
from charts import cumulative_profit_series, player_session_series
from db import database_extensions_available, db
from models import SessionSummary
from services import apply_rank_changes, build_leaderboard, build_session_summaries, session_events
from utils import cents_to_dollars, session_label, session_sort_key

leagues_bp = Blueprint("leagues", __name__)

LEAGUE_EVENT_TYPES = [
    ("buyin", "Buy-in"),
    ("front", "Front"),
    ("rollover_in", "Rollover-in"),
    ("payout_carry_in", "Payout carry-in"),
    ("cashout", "Cashout result"),
    ("paid_out", "Paid out cash"),
    ("rollover_out", "Rollover-out"),
    ("debt_repayment", "Debt repayment"),
    ("writeoff", "Write-off"),
    ("note", "Note"),
]


def db_ready() -> bool:
    return database_extensions_available() and db is not None


def league_url_values(league) -> dict[str, str]:
    return {"league_ref": league.url_ref}


def split_league_ref(league_ref: str) -> tuple[str, str]:
    slug, separator, public_key = league_ref.rpartition("-")
    if not separator or not slug or not public_key:
        abort(404)
    return slug, public_key


def require_league(league_ref: str, allowed_roles: set[str]):
    from league_repositories import find_league_by_public_key, user_has_league_role

    _slug, public_key = split_league_ref(league_ref)
    league = find_league_by_public_key(public_key)
    if league is None:
        abort(404)

    user_id = current_user_id() or ""
    if not user_has_league_role(user_id, league.id, allowed_roles):
        abort(403)

    return league


def get_league_with_visibility_gate(league_ref: str):
    """Load league; if private, enforce login + membership. Returns (league, None) or (None, redirect)."""
    from league_repositories import find_league_by_public_key, user_has_league_role

    _slug, public_key = split_league_ref(league_ref)
    league = find_league_by_public_key(public_key)
    if league is None:
        abort(404)

    if league.visibility != "public":
        user_id = current_user_id()
        if not user_id:
            return None, redirect(url_for("account.login", next=request.path))
        if not user_has_league_role(user_id, league.id, {"owner", "manager", "viewer"}):
            abort(403)

    return league, None


def parse_amount_cents(raw_amount: str) -> int | None:
    try:
        return int(round(float(raw_amount.strip() or "0") * 100))
    except ValueError:
        return None


def empty_session_summary(session) -> SessionSummary:
    return SessionSummary(
        session_id=f"{session.session_date.isoformat()}-{session.sequence_on_date:02d}",
        session_date=session.session_date.isoformat(),
        entries=[],
        status=session.status,
        opened_at=session.opened_at.isoformat() if session.opened_at else "",
    )


def session_ref_map(league_id: str) -> dict[str, str]:
    from ledger_repositories import session_event_ref
    from league_repositories import list_sessions_for_league

    return {session_event_ref(session): session.id for session in list_sessions_for_league(league_id)}


@leagues_bp.get("/leagues")
@login_required
def index():
    if not db_ready():
        flash("League database is not available.", "error")
        return render_template("leagues_index.html", leagues=[])

    from league_repositories import list_leagues_for_user
    from ledger_repositories import list_event_rows_for_league

    memberships = list_leagues_for_user(current_user_id() or "")
    league_summaries = []
    total_sessions = 0
    total_players = 0
    total_events = 0
    total_open_items_cents = 0
    live_count = 0
    for league, membership in memberships:
        events = list_event_rows_for_league(league.id)
        summaries = build_session_summaries(events)
        leaderboard = build_leaderboard(summaries)
        live_sessions = [session for session in summaries if session.status == "open"]
        latest_session = sorted(summaries, key=session_sort_key, reverse=True)[0] if summaries else None
        players_count = len({
            entry.player_name
            for session in summaries
            for entry in session.entries
        })
        open_items_cents = sum(
            session.total_current_due_to_player_cents
            + session.total_current_due_to_house_cents
            for session in summaries
        )
        total_sessions += len(summaries)
        total_players += players_count
        total_events += len(events)
        total_open_items_cents += open_items_cents
        live_count += len(live_sessions)
        league_summaries.append(
            {
                "league": league,
                "membership": membership,
                "sessions": summaries,
                "live_session": live_sessions[0] if live_sessions else None,
                "latest_session": latest_session,
                "top_players": leaderboard[:3],
                "leader": leaderboard[0] if leaderboard else None,
                "players_count": players_count,
                "sessions_count": len(summaries),
                "events_count": len(events),
                "cash_paid_out_cents": sum(
                    session.total_paid_out_cents for session in summaries
                ),
                "open_items_cents": open_items_cents,
            }
        )
    page_summary = {
        "league_count": len(league_summaries),
        "live_count": live_count,
        "players_count": total_players,
        "sessions_count": total_sessions,
        "events_count": total_events,
        "open_items_cents": total_open_items_cents,
    }
    return render_template(
        "leagues_index.html",
        leagues=league_summaries,
        page_summary=page_summary,
        session_label=session_label,
    )


@leagues_bp.route("/leagues/new", methods=["GET", "POST"])
@login_required
def new():
    if not db_ready():
        flash("League database is not available.", "error")
        return render_template("league_new.html", form={})

    form = {
        "name": request.form.get("name", "").strip(),
        "description": request.form.get("description", "").strip(),
    }

    if request.method == "POST":
        from db_models import User
        from league_repositories import create_league, unique_league_slug

        owner = db.session.get(User, current_user_id())
        if owner is None:
            flash("Login required.", "error")
            return redirect(url_for("account.login"))

        if len(form["name"]) < 2:
            flash("League name must be at least 2 characters.", "error")
        else:
            slug = unique_league_slug(form["name"])
            league = create_league(
                owner=owner,
                name=form["name"],
                slug=slug,
                description=form["description"] or None,
            )
            db.session.commit()
            flash("League created.", "success")
            return redirect(url_for("leagues.dashboard", **league_url_values(league)))

    return render_template("league_new.html", form=form)


@leagues_bp.get("/l/<league_ref>")
def dashboard(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from league_repositories import league_counts, user_has_league_role
    from ledger_repositories import list_event_rows_for_league

    league, resp = get_league_with_visibility_gate(league_ref)
    if resp:
        return resp
    is_owner = user_has_league_role(current_user_id() or "", league.id, {"owner"})

    all_sessions = build_session_summaries(list_event_rows_for_league(league.id))
    closed_sessions = [s for s in all_sessions if not s.is_open]
    closed_count = len(closed_sessions)

    total_cash_in = sum(s.total_real_cash_in_cents for s in closed_sessions)
    total_paid_out = sum(s.total_paid_out_cents for s in closed_sessions)
    total_fronts = sum(s.total_front_cents for s in all_sessions)
    closed_entries = sum(len(s.entries) for s in closed_sessions)
    all_entries = sum(len(s.entries) for s in all_sessions)

    # Avg sessions per month since the first session
    session_date_strs = [s.session_date[:10] for s in all_sessions if s.session_date]
    avg_sessions_per_month = 0.0
    if session_date_strs:
        first_date = date.fromisoformat(min(session_date_strs))
        today_d = date.today()
        months_elapsed = (today_d.year - first_date.year) * 12 + (today_d.month - first_date.month) + 1
        avg_sessions_per_month = round(len(all_sessions) / months_elapsed, 1)

    # Session calendar data: date → count of sessions on that date
    sessions_by_date: dict[str, int] = {}
    for s in all_sessions:
        if s.session_date:
            d = s.session_date[:10]
            sessions_by_date[d] = sessions_by_date.get(d, 0) + 1
    first_session_year = int(min(sessions_by_date)[:4]) if sessions_by_date else date.today().year

    cash_stats = {
        "total_cash_in": total_cash_in,
        "total_paid_out": total_paid_out,
        "total_fronts": total_fronts,
        "avg_pot": total_cash_in // closed_count if closed_count else 0,
        "avg_players": round(all_entries / len(all_sessions)) if all_sessions else 0,
        "avg_buyin": sum(s.total_buy_in_cents for s in closed_sessions) // closed_entries if closed_entries else 0,
        "biggest_pot": max((s.total_real_cash_in_cents for s in all_sessions), default=0),
        "avg_sessions_per_month": avg_sessions_per_month,
        "session_map": sessions_by_date,
        "first_session_year": first_session_year,
        "has_data": closed_count > 0,
        "has_sessions": bool(all_sessions),
    }

    return render_template(
        "league_dashboard.html",
        league=league,
        counts=league_counts(league.id),
        is_owner=is_owner,
        cash_stats=cash_stats,
    )


@leagues_bp.get("/l/<league_id>/<league_slug>")
@login_required
def legacy_dashboard_redirect(league_id: str, league_slug: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from league_repositories import find_league_by_id, user_has_league_role

    league = find_league_by_id(league_id)
    if league is None:
        abort(404)
    if not user_has_league_role(current_user_id() or "", league.id, {"owner", "manager", "viewer"}):
        abort(403)

    return redirect(url_for("leagues.dashboard", **league_url_values(league)), code=301)


@leagues_bp.get("/l/<league_ref>/leaderboard")
def leaderboard(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from config import ELIGIBLE_MIN_SESSIONS
    from ledger_repositories import list_event_rows_for_league
    from league_repositories import list_players_for_league, user_has_league_role

    league, resp = get_league_with_visibility_gate(league_ref)
    if resp:
        return resp
    is_owner = user_has_league_role(current_user_id() or "", league.id, {"owner"})
    all_sessions = build_session_summaries(list_event_rows_for_league(league.id))
    ordered_sessions = sorted(all_sessions, key=session_sort_key)

    session_ids = [session.session_id for session in ordered_sessions]
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

    board = apply_rank_changes(
        build_leaderboard(filtered_sessions),
        build_leaderboard(previous_sessions),
    )
    eligible_count = sum(
        1 for player in board if player.sessions_played >= ELIGIBLE_MIN_SESSIONS
    )
    all_count = len(board)
    recent_sessions_slice = filtered_sessions[-5:]
    recent_count = len({
        entry.player_name
        for session in recent_sessions_slice
        for entry in session.entries
    })

    if mode == "recent":
        main_board = build_leaderboard(recent_sessions_slice)
        provisional_board = []
    elif mode == "eligible":
        main_board = [
            player
            for player in board
            if player.sessions_played >= ELIGIBLE_MIN_SESSIONS
        ]
        provisional_board = [
            player
            for player in board
            if player.sessions_played < ELIGIBLE_MIN_SESSIONS
        ]
    else:
        main_board = board
        provisional_board = []

    chart_data = cumulative_profit_series(filtered_sessions)
    cash_paid_out_cents = sum(session.total_paid_out_cents for session in all_sessions)

    return render_template(
        "league_leaderboard.html",
        league=league,
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
        session_ids=session_ref_map(league.id),
        player_ids={
            player.display_name: player.id
            for player in list_players_for_league(league.id)
        },
        is_owner=is_owner,
    )


@leagues_bp.route("/l/<league_ref>/ledger", methods=["GET", "POST"])
@login_required
def ledger(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from ledger_repositories import (
        append_ledger_event,
        list_all_event_rows_for_league,
        list_event_rows_for_league,
    )
    from league_repositories import (
        find_player_for_league,
        find_session_for_league,
        list_players_for_league,
        user_has_league_role,
    )

    league = require_league(
        league_ref,
        {"owner", "manager"} if request.method == "POST" else {"owner", "manager", "viewer"},
    )
    can_manage = user_has_league_role(current_user_id() or "", league.id, {"owner", "manager"})
    is_owner = user_has_league_role(current_user_id() or "", league.id, {"owner"})

    rows = list_event_rows_for_league(league.id)
    summaries = build_session_summaries(rows)
    session_ids = session_ref_map(league.id)
    player_ids = {player.display_name: player.id for player in list_players_for_league(league.id)}
    debt_entries = [
        {"session": session, "entry": entry}
        for session in summaries
        for entry in session.entries
        if entry.current_due_to_house_cents > 0
    ]
    due_to_player_items = [
        {"session": session, "entry": entry}
        for session in summaries
        for entry in session.entries
        if entry.current_due_to_player_cents > 0
    ]
    open_sessions = [s for s in summaries if s.is_open]

    if request.method == "POST":
        session_id = request.form.get("session_id", "").strip()
        player_id = request.form.get("player_id", "").strip()
        event_type = request.form.get("event_type", "").strip()
        note = request.form.get("note", "").strip()
        amount_cents = parse_amount_cents(request.form.get("amount", "0"))

        session = find_session_for_league(league.id, session_id)
        player = find_player_for_league(league.id, player_id)
        if session is None or player is None:
            abort(404)
        if event_type not in {"debt_repayment", "writeoff"}:
            flash("Select a valid debt resolution type.", "error")
        elif amount_cents is None or amount_cents <= 0:
            flash("Amount must be greater than zero.", "error")
        else:
            session_ref = next(
                (
                    ref
                    for ref, db_session_id in session_ids.items()
                    if db_session_id == session.id
                ),
                "",
            )
            target_summary = next(
                (summary for summary in summaries if summary.session_id == session_ref),
                None,
            )
            target_entry = (
                next(
                    (
                        entry
                        for entry in target_summary.entries
                        if entry.player_name == player.display_name
                    ),
                    None,
                )
                if target_summary is not None
                else None
            )
            if target_entry is None or target_entry.current_due_to_house_cents <= 0:
                flash("That player does not have an outstanding debt in this session.", "error")
            elif amount_cents > target_entry.current_due_to_house_cents:
                flash(
                    f"Debt resolution cannot exceed {cents_to_dollars(target_entry.current_due_to_house_cents)}.",
                    "error",
                )
            else:
                append_ledger_event(
                    league.id,
                    session.id,
                    event_type,
                    amount_cents,
                    current_user_id() or "",
                    player_id=player.id,
                    note=note or ("Debt repaid." if event_type == "debt_repayment" else "Debt written off."),
                )
                db.session.commit()
                flash("Debt resolution recorded.", "success")
                return redirect(url_for("leagues.ledger", **league_url_values(league)))

    cash_in_cents = sum(s.total_real_cash_in_cents for s in summaries)
    cash_out_cents = sum(s.total_real_cash_out_cents for s in summaries)
    due_to_players_cents = sum(s.total_current_due_to_player_cents for s in summaries)
    due_to_house_cents = sum(s.total_current_due_to_house_cents for s in summaries)
    totals = {
        "cash_in_cents": cash_in_cents,
        "cash_out_cents": cash_out_cents,
        "due_to_players_cents": due_to_players_cents,
        "due_to_house_cents": due_to_house_cents,
        "book_held_cents": cash_in_cents - cash_out_cents,
        "net_position_cents": (cash_in_cents - cash_out_cents) + due_to_house_cents - due_to_players_cents,
        "collected_cents": sum(s.total_debt_repayment_cents for s in summaries),
        "written_off_cents": sum(s.total_writeoff_cents for s in summaries),
        "events": len(rows),
    }

    all_rows = list_all_event_rows_for_league(league.id)

    return render_template(
        "league_ledger.html",
        league=league,
        totals=totals,
        sessions=summaries,
        debt_entries=debt_entries,
        due_to_player_items=due_to_player_items,
        open_sessions=open_sessions,
        raw_events=list(reversed(all_rows)),
        session_label=session_label,
        session_ids=session_ids,
        player_ids=player_ids,
        can_manage=can_manage,
        is_owner=is_owner,
    )


@leagues_bp.post("/l/<league_ref>/events/<event_id>/void")
@login_required
def void_event(league_ref: str, event_id: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from ledger_repositories import void_ledger_event

    league = require_league(league_ref, {"owner"})
    reason = request.form.get("void_reason", "").strip()
    session_id = None
    try:
        event = void_ledger_event(event_id, league.id, current_user_id() or "", reason)
        session_id = event.session_id
        db.session.commit()
        flash("Event voided.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    if session_id:
        return redirect(url_for("leagues.session_detail", **league_url_values(league), session_id=session_id))
    return redirect(url_for("leagues.ledger", **league_url_values(league)))


@leagues_bp.get("/l/<league_ref>/players/<player_id>")
def player_detail(league_ref: str, player_id: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from ledger_repositories import list_event_rows_for_league
    from league_repositories import find_player_for_league, user_has_league_role

    league, resp = get_league_with_visibility_gate(league_ref)
    if resp:
        return resp
    user_id = current_user_id() or ""
    is_owner = user_has_league_role(user_id, league.id, {"owner"})
    can_manage = user_has_league_role(user_id, league.id, {"owner", "manager"})
    player_record = find_player_for_league(league.id, player_id)
    if player_record is None:
        abort(404)

    all_sessions = build_session_summaries(list_event_rows_for_league(league.id))
    board = build_leaderboard(all_sessions)
    player_stats = next(
        (player for player in board if player.player_name == player_record.display_name),
        None,
    )
    if player_stats is None:
        flash("That player has no ledger events yet.", "error")
        return redirect(url_for("leagues.players", **league_url_values(league)))

    player_rank = next(
        (
            index
            for index, ranked_player in enumerate(board, start=1)
            if ranked_player.player_name == player_record.display_name
        ),
        None,
    )
    player_sessions = [
        {"session": session, "entry": entry}
        for session in sorted(all_sessions, key=session_sort_key, reverse=True)
        for entry in session.entries
        if entry.player_name == player_record.display_name
    ]

    return render_template(
        "league_player_detail.html",
        league=league,
        player_record=player_record,
        player=player_stats,
        player_rank=player_rank,
        chart_data=player_session_series(all_sessions, player_record.display_name),
        player_sessions=player_sessions,
        session_label=session_label,
        session_ids=session_ref_map(league.id),
        is_owner=is_owner,
        can_manage=can_manage,
    )


@leagues_bp.route("/l/<league_ref>/players", methods=["GET", "POST"])
def players(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from league_repositories import (
        create_player,
        list_players_for_league,
        player_name_exists,
        unique_player_slug,
        user_has_league_role,
    )

    if request.method == "POST":
        league = require_league(league_ref, {"owner", "manager"})
    else:
        league, resp = get_league_with_visibility_gate(league_ref)
        if resp:
            return resp
    user_id = current_user_id() or ""
    can_manage = user_has_league_role(user_id, league.id, {"owner", "manager"})
    is_owner = user_has_league_role(user_id, league.id, {"owner"})
    form = {
        "display_name": request.form.get("display_name", "").strip(),
        "slug": request.form.get("slug", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }

    if request.method == "POST":
        if len(form["display_name"]) < 2:
            flash("Player name must be at least 2 characters.", "error")
        elif player_name_exists(league.id, form["display_name"]):
            flash("A player with that name already exists in this league.", "error")
        else:
            player = create_player(
                league.id,
                form["display_name"],
                unique_player_slug(league.id, form["display_name"], form["slug"] or None),
            )
            player.notes = form["notes"] or None
            db.session.commit()
            flash("Player added.", "success")
            return redirect(url_for("leagues.players", **league_url_values(league)))

    from ledger_repositories import list_event_rows_for_league

    all_sessions = build_session_summaries(list_event_rows_for_league(league.id))
    board = build_leaderboard(all_sessions)
    stats_by_name = {p.player_name: p for p in board}

    return render_template(
        "league_players.html",
        league=league,
        players=list_players_for_league(league.id),
        stats_by_name=stats_by_name,
        form=form,
        can_manage=can_manage,
        is_owner=is_owner,
    )


@leagues_bp.post("/l/<league_ref>/players/<player_id>/archive")
@login_required
def archive_player(league_ref: str, player_id: str):
    return update_player_status(league_ref, player_id, "archived", "Player archived.")


@leagues_bp.post("/l/<league_ref>/players/<player_id>/reactivate")
@login_required
def reactivate_player(league_ref: str, player_id: str):
    return update_player_status(league_ref, player_id, "active", "Player reactivated.")


def update_player_status(league_ref: str, player_id: str, status: str, message: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from league_repositories import find_player_for_league, set_player_status

    league = require_league(league_ref, {"owner", "manager"})
    player = find_player_for_league(league.id, player_id)
    if player is None:
        abort(404)

    set_player_status(player, status)
    db.session.commit()
    flash(message, "success")
    return redirect(url_for("leagues.players", **league_url_values(league)))


@leagues_bp.post("/l/<league_ref>/players/<player_id>/edit")
@login_required
def edit_player(league_ref: str, player_id: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from league_repositories import find_player_for_league, player_name_taken, update_player

    league = require_league(league_ref, {"owner", "manager"})
    player = find_player_for_league(league.id, player_id)
    if player is None:
        abort(404)

    new_name = request.form.get("display_name", "").strip()
    new_notes = request.form.get("notes", "").strip() or None

    if len(new_name) < 2:
        flash("Player name must be at least 2 characters.", "error")
    elif player_name_taken(league.id, new_name, player.id):
        flash("A player with that name already exists in this league.", "error")
    else:
        update_player(player, new_name, new_notes)
        db.session.commit()
        flash("Player updated.", "success")

    return redirect(url_for("leagues.players", **league_url_values(league)))


@leagues_bp.route("/l/<league_ref>/sessions", methods=["GET", "POST"])
def sessions(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from ledger_repositories import append_ledger_event
    from league_repositories import (
        create_poker_session,
        list_sessions_for_league,
        user_has_league_role,
    )

    if request.method == "POST":
        league = require_league(league_ref, {"owner", "manager"})
    else:
        league, resp = get_league_with_visibility_gate(league_ref)
        if resp:
            return resp
    user_id = current_user_id() or ""
    can_manage = user_has_league_role(user_id, league.id, {"owner", "manager"})
    is_owner = user_has_league_role(user_id, league.id, {"owner"})
    form = {
        "session_date": request.form.get("session_date", date.today().isoformat()).strip(),
        "label": request.form.get("label", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "status": request.form.get("status", "open").strip(),
    }

    if request.method == "POST":
        try:
            session_date = date.fromisoformat(form["session_date"])
        except ValueError:
            flash("Session date must be a valid date.", "error")
        else:
            status = "closed" if form["status"] == "closed" else "open"
            session = create_poker_session(
                league.id,
                session_date,
                status=status,
            )
            session.label = form["label"] or None
            session.notes = form["notes"] or None
            if status == "open":
                from league_repositories import set_session_status

                set_session_status(session, "open")

            db.session.flush()
            if status == "open":
                append_ledger_event(
                    league.id,
                    session.id,
                    "session_open",
                    0,
                    current_user_id() or "",
                    note="Session created.",
                )
            db.session.commit()
            flash(f"Created {session.display_label}.", "success")
            return redirect(url_for("leagues.sessions", **league_url_values(league)))

    from db_models import LedgerEvent
    from ledger_repositories import list_event_rows_for_league

    all_sessions = list_sessions_for_league(league.id)
    summaries = build_session_summaries(list_event_rows_for_league(league.id))
    ref_to_db_id = {
        f"{s.session_date.isoformat()}-{s.sequence_on_date:02d}": s.id
        for s in all_sessions
    }
    db_id_to_summary = {
        ref_to_db_id[sm.session_id]: sm
        for sm in summaries
        if sm.session_id in ref_to_db_id
    }
    empty_count = sum(
        1 for s in all_sessions
        if s.id not in db_id_to_summary or not db_id_to_summary[s.id].entries
    )

    return render_template(
        "league_sessions.html",
        league=league,
        sessions=all_sessions,
        db_id_to_summary=db_id_to_summary,
        form=form,
        can_manage=can_manage,
        is_owner=is_owner,
        empty_count=empty_count,
    )


@leagues_bp.post("/l/<league_ref>/sessions/prune-empty")
@login_required
def prune_empty_sessions(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from db_models import LedgerEvent, PokerSession
    from league_repositories import list_sessions_for_league

    league = require_league(league_ref, {"owner", "manager"})

    all_sessions = list_sessions_for_league(league.id)
    session_ids_with_players = {
        row[0]
        for row in db.session.query(LedgerEvent.session_id).filter(
            LedgerEvent.league_id == league.id,
            LedgerEvent.player_id.isnot(None),
            LedgerEvent.voided_at.is_(None),
        ).all()
    }
    empty_sessions = [s for s in all_sessions if s.id not in session_ids_with_players]

    if not empty_sessions:
        flash("No empty sessions to prune.", "success")
        return redirect(url_for("leagues.sessions", **league_url_values(league)))

    for session in empty_sessions:
        db.session.delete(session)
    db.session.commit()

    n = len(empty_sessions)
    flash(f"Pruned {n} empty session{'s' if n != 1 else ''}.", "success")
    return redirect(url_for("leagues.sessions", **league_url_values(league)))


@leagues_bp.post("/l/<league_ref>/sessions/<session_id>/delete")
@login_required
def delete_session(league_ref: str, session_id: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from league_repositories import find_session_for_league

    league = require_league(league_ref, {"owner"})
    session = find_session_for_league(league.id, session_id)
    if session is None:
        abort(404)
    label = session.display_label
    db.session.delete(session)
    db.session.commit()
    flash(f"Deleted {label} and all its events.", "success")
    return redirect(url_for("leagues.sessions", **league_url_values(league)))


@leagues_bp.post("/l/<league_ref>/sessions/<session_id>/edit")
@login_required
def edit_session(league_ref: str, session_id: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from league_repositories import find_session_for_league

    league = require_league(league_ref, {"owner", "manager"})
    session = find_session_for_league(league.id, session_id)
    if session is None:
        abort(404)

    new_label = request.form.get("label", "").strip() or None
    new_notes = request.form.get("notes", "").strip() or None
    new_date_str = request.form.get("session_date", "").strip()

    try:
        new_date = date.fromisoformat(new_date_str)
    except ValueError:
        flash("Invalid session date.", "error")
        return redirect(url_for("leagues.session_detail", league_ref=league.url_ref, session_id=session_id))

    if new_date != session.session_date:
        from db_models import PokerSession as _PS
        max_seq = db.session.query(db.func.max(_PS.sequence_on_date)).filter(
            _PS.league_id == league.id,
            _PS.session_date == new_date,
            _PS.id != session.id,
        ).scalar()
        session.sequence_on_date = int(max_seq or 0) + 1
        session.session_date = new_date

    session.label = new_label
    session.notes = new_notes
    db.session.commit()
    flash("Session updated.", "success")
    return redirect(url_for("leagues.session_detail", league_ref=league.url_ref, session_id=session_id))


@leagues_bp.route("/l/<league_ref>/sessions/<session_id>", methods=["GET", "POST"])
@login_required
def session_detail(league_ref: str, session_id: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from ledger_repositories import append_ledger_event, list_all_event_rows_for_session, list_event_rows_for_session
    from league_repositories import (
        find_session_for_league,
        list_players_for_league,
        user_has_league_role,
    )

    league = require_league(
        league_ref,
        {"owner", "manager"} if request.method == "POST" else {"owner", "manager", "viewer"},
    )
    session = find_session_for_league(league.id, session_id)
    if session is None:
        abort(404)

    can_manage = user_has_league_role(current_user_id() or "", league.id, {"owner", "manager"})
    is_owner = user_has_league_role(current_user_id() or "", league.id, {"owner"})
    players = [player for player in list_players_for_league(league.id) if player.status == "active"]
    append_form = {
        "player_id": request.form.get("player_id", "").strip(),
        "event_type": request.form.get("event_type", "buyin").strip(),
        "amount": request.form.get("amount", "").strip(),
        "note": request.form.get("note", "").strip(),
    }

    if request.method == "POST":
        if session.status != "open":
            flash("That session is closed. Reopen it before adding events.", "error")
        elif append_form["event_type"] not in {event_type for event_type, _ in LEAGUE_EVENT_TYPES}:
            flash("Select a valid event type.", "error")
        else:
            amount_cents = parse_amount_cents(append_form["amount"])
            if amount_cents is None:
                flash("Amount must be a number.", "error")
            elif amount_cents <= 0 and append_form["event_type"] != "note":
                flash("Amount must be greater than zero.", "error")
            else:
                player_id = append_form["player_id"] or None
                if append_form["event_type"] != "note" and player_id is None:
                    flash("Select a player for this event.", "error")
                else:
                    if player_id is not None and not any(player.id == player_id for player in players):
                        abort(404)

                    append_ledger_event(
                        league.id,
                        session.id,
                        append_form["event_type"],
                        amount_cents,
                        current_user_id() or "",
                        player_id=player_id,
                        note=append_form["note"],
                    )
                    db.session.commit()
                    flash("Ledger event added.", "success")
                    return redirect(
                        url_for(
                            "leagues.session_detail",
                            **league_url_values(league),
                            session_id=session.id,
                        )
                    )

    rows = list_event_rows_for_session(league.id, session.id)
    summaries = build_session_summaries(rows)
    summary = summaries[0] if summaries else empty_session_summary(session)
    all_rows = list_all_event_rows_for_session(league.id, session.id)

    return render_template(
        "league_session_detail.html",
        league=league,
        session_model=session,
        session=summary,
        players=players,
        raw_events=all_rows,
        event_types=LEAGUE_EVENT_TYPES,
        append_form=append_form,
        can_manage=can_manage,
        is_owner=is_owner,
        session_label=session_label,
    )


@leagues_bp.get("/l/<league_ref>/sessions/<session_id>/view")
def session_public_view(league_ref: str, session_id: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from charts import session_breakdown_series
    from ledger_repositories import list_event_rows_for_league, list_event_rows_for_session
    from league_repositories import find_league_by_public_key, find_session_for_league, list_sessions_for_league, user_has_league_role

    _slug, public_key = split_league_ref(league_ref)
    league = find_league_by_public_key(public_key)
    if league is None:
        abort(404)

    if league.visibility != "public":
        user_id = current_user_id()
        if not user_id:
            return redirect(url_for("account.login", next=request.path))
        if not user_has_league_role(user_id, league.id, {"owner", "manager", "viewer"}):
            abort(403)

    session = find_session_for_league(league.id, session_id)
    if session is None:
        abort(404)

    rows = list_event_rows_for_session(league.id, session.id)
    summaries = build_session_summaries(rows)
    summary = summaries[0] if summaries else empty_session_summary(session)

    all_sessions = sorted(
        build_session_summaries(list_event_rows_for_league(league.id)),
        key=session_sort_key,
    )
    session_ref = f"{session.session_date.isoformat()}-{session.sequence_on_date:02d}"
    chrono_idx = next((i for i, s in enumerate(all_sessions) if s.session_id == session_ref), 0)
    session_number = chrono_idx + 1

    all_db_sessions = list_sessions_for_league(league.id)
    ref_to_db_id = {
        f"{s.session_date.isoformat()}-{s.sequence_on_date:02d}": s.id
        for s in all_db_sessions
    }

    prev_summary = all_sessions[chrono_idx - 1] if chrono_idx > 0 else None
    next_summary = all_sessions[chrono_idx + 1] if chrono_idx < len(all_sessions) - 1 else None

    return render_template(
        "league_session_view.html",
        league=league,
        session_model=session,
        session=summary,
        session_number=session_number,
        raw_events=session_events(rows, summary.session_id),
        chart_data=session_breakdown_series(summary),
        session_label=session_label,
        prev_session_id=ref_to_db_id.get(prev_summary.session_id) if prev_summary else None,
        next_session_id=ref_to_db_id.get(next_summary.session_id) if next_summary else None,
        is_owner=False,
    )


@leagues_bp.post("/l/<league_ref>/sessions/<session_id>/open")
@login_required
def open_league_session(league_ref: str, session_id: str):
    return update_session_status(league_ref, session_id, "open", "Session opened.")


@leagues_bp.post("/l/<league_ref>/sessions/<session_id>/close")
@login_required
def close_league_session(league_ref: str, session_id: str):
    return update_session_status(league_ref, session_id, "closed", "Session closed.")


def update_session_status(league_ref: str, session_id: str, status: str, message: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from ledger_repositories import append_ledger_event
    from league_repositories import find_session_for_league, set_session_status

    league = require_league(league_ref, {"owner", "manager"})
    session = find_session_for_league(league.id, session_id)
    if session is None:
        abort(404)

    if session.status == status:
        flash(f"Session is already {status}.", "success")
        return redirect(url_for("leagues.sessions", **league_url_values(league)))

    set_session_status(session, status)
    append_ledger_event(
        league.id,
        session.id,
        "session_open" if status == "open" else "session_close",
        0,
        current_user_id() or "",
        note=message,
    )
    db.session.commit()
    flash(message, "success")
    return redirect(url_for("leagues.sessions", **league_url_values(league)))


@leagues_bp.route("/l/<league_ref>/settings", methods=["GET", "POST"])
@login_required
def league_settings(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    league = require_league(league_ref, {"owner"})

    form = {
        "name": league.name,
        "description": league.description or "",
        "visibility": league.visibility,
    }

    if request.method == "POST":
        form = {
            "name": request.form.get("name", "").strip(),
            "description": request.form.get("description", "").strip(),
            "visibility": request.form.get("visibility", "private").strip(),
        }
        if len(form["name"]) < 2:
            flash("League name must be at least 2 characters.", "error")
        elif form["visibility"] not in ("private", "public"):
            flash("Invalid visibility value.", "error")
        else:
            from utils import slugify

            league.name = form["name"]
            league.slug = slugify(form["name"])
            league.description = form["description"] or None
            league.visibility = form["visibility"]
            db.session.commit()
            flash("League settings saved.", "success")
            return redirect(url_for("leagues.league_settings", league_ref=league.url_ref))

    from league_repositories import list_members_for_league

    members = list_members_for_league(league.id)
    return render_template("league_settings.html", league=league, form=form, is_owner=True, members=members)


@leagues_bp.post("/l/<league_ref>/settings/invite")
@login_required
def invite_member(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from auth import generate_invite_token
    from emails import send_league_invite
    from flask import current_app
    from league_repositories import find_membership, find_user_by_email

    league = require_league(league_ref, {"owner"})
    email = normalize_email(request.form.get("email", ""))
    role = request.form.get("role", "manager").strip()

    if not email or "@" not in email:
        flash("Enter a valid email address.", "error")
        return redirect(url_for("leagues.league_settings", league_ref=league.url_ref))

    if role not in ("manager", "viewer"):
        flash("Invalid role.", "error")
        return redirect(url_for("leagues.league_settings", league_ref=league.url_ref))

    existing_user = find_user_by_email(email)
    if existing_user:
        existing_membership = find_membership(league.id, existing_user.id)
        if existing_membership:
            flash(f"{email} is already a member of this league.", "error")
            return redirect(url_for("leagues.league_settings", league_ref=league.url_ref))

    token = generate_invite_token(league.id, email, role, current_user_id() or "")
    base_url = current_app.config.get("APP_BASE_URL", "").rstrip("/")
    invite_url = f"{base_url}{url_for('account.accept_invite', token=token)}"

    try:
        send_league_invite(email, league.name, invite_url, current_user_id() or "")
        flash(f"Invitation sent to {email}.", "success")
    except Exception:
        flash("Failed to send invitation email. Check your mail configuration.", "error")

    return redirect(url_for("leagues.league_settings", league_ref=league.url_ref))


@leagues_bp.post("/l/<league_ref>/settings/members/<user_id>/remove")
@login_required
def remove_member(league_ref: str, user_id: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from league_repositories import remove_league_member

    league = require_league(league_ref, {"owner"})

    if user_id == current_user_id():
        flash("You cannot remove yourself from the league.", "error")
        return redirect(url_for("leagues.league_settings", league_ref=league.url_ref))

    remove_league_member(league.id, user_id)
    db.session.commit()
    flash("Member removed.", "success")
    return redirect(url_for("leagues.league_settings", league_ref=league.url_ref))


@leagues_bp.post("/l/<league_ref>/archive")
@login_required
def archive_league(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from db_models import utc_now

    league = require_league(league_ref, {"owner"})
    confirm_name = request.form.get("confirm_name", "").strip()

    if confirm_name != league.name:
        flash("League name did not match. Archive cancelled.", "error")
        return redirect(url_for("leagues.league_settings", league_ref=league_ref))

    league.archived_at = utc_now()
    db.session.commit()
    flash(f'"{league.name}" has been archived.', "success")
    return redirect(url_for("leagues.index"))


@leagues_bp.get("/l/<league_ref>/ledger/export")
@login_required
def export_ledger_csv(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from ledger_repositories import list_event_rows_for_league
    from storage import CSV_HEADERS

    league = require_league(league_ref, {"owner", "manager", "viewer"})
    rows = list_event_rows_for_league(league.id)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADERS)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row[k] for k in CSV_HEADERS})

    filename = f"ledger_{league.slug}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@leagues_bp.post("/l/<league_ref>/ledger/import")
@login_required
def import_ledger_csv(league_ref: str):
    if not db_ready():
        flash("League database is not available.", "error")
        return redirect(url_for("public.home"))

    from db_models import CANONICAL_EVENT_TYPES, canonical_event_type
    from ledger_repositories import (
        append_ledger_event,
        list_ledger_events_for_league,
        session_event_ref,
    )
    from league_repositories import create_player, list_players_for_league, list_sessions_for_league, unique_player_slug
    from storage import CSV_HEADERS

    league = require_league(league_ref, {"owner", "manager"})

    uploaded = request.files.get("csv_file")
    if uploaded is None or uploaded.filename == "":
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("leagues.ledger", **league_url_values(league)))

    if not uploaded.filename.lower().endswith(".csv"):
        flash("Only CSV files are accepted.", "error")
        return redirect(url_for("leagues.ledger", **league_url_values(league)))

    try:
        text = uploaded.stream.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("CSV must be valid UTF-8.", "error")
        return redirect(url_for("leagues.ledger", **league_url_values(league)))

    lines = text.splitlines()
    if not lines:
        flash("CSV file is empty.", "error")
        return redirect(url_for("leagues.ledger", **league_url_values(league)))

    try:
        header = next(csv.reader(lines))
    except Exception:
        flash("Could not parse CSV header.", "error")
        return redirect(url_for("leagues.ledger", **league_url_values(league)))

    if header != CSV_HEADERS:
        flash(f"CSV header mismatch. Expected: {', '.join(CSV_HEADERS)}", "error")
        return redirect(url_for("leagues.ledger", **league_url_values(league)))

    from db_models import PokerSession, make_session

    sessions = list_sessions_for_league(league.id)
    session_by_ref = {session_event_ref(s): s for s in sessions}

    players = list_players_for_league(league.id)
    player_by_name = {p.display_name.strip().casefold(): p for p in players}

    existing_legacy_ids = {
        e.legacy_event_id
        for e in list_ledger_events_for_league(league.id)
        if e.legacy_event_id
    }

    # Auto-create any sessions referenced in the CSV that don't exist yet.
    # Refs are "YYYY-MM-DD-NN" so we can recover exact date and sequence.
    missing_refs: set[str] = set()
    for row in csv.DictReader(lines):
        ref = row.get("session_id", "").strip()
        if ref and ref not in session_by_ref:
            missing_refs.add(ref)

    sessions_created = 0
    for ref in sorted(missing_refs):
        try:
            date_part, seq_part = ref.rsplit("-", 1)
            session_date = date.fromisoformat(date_part)
            sequence = int(seq_part)
        except (ValueError, IndexError):
            continue  # malformed ref — row will produce a clear error below

        existing = PokerSession.query.filter_by(
            league_id=league.id,
            session_date=session_date,
            sequence_on_date=sequence,
        ).one_or_none()
        if existing:
            session_by_ref[ref] = existing
            continue

        new_session = make_session(
            league_id=league.id,
            session_date=session_date,
            sequence_on_date=sequence,
            status="closed",
        )
        db.session.add(new_session)
        db.session.flush()
        session_by_ref[ref] = new_session
        sessions_created += 1

    # Auto-create any players referenced in the CSV that don't exist yet.
    # Only rows that need a player (not note/session_open/session_close) are considered.
    non_player_types = {"note", "session_open", "session_close"}
    missing_players: set[str] = set()
    for row in csv.DictReader(lines):
        raw_type = row.get("event_type", "").strip()
        if canonical_event_type(raw_type) in non_player_types:
            continue
        name = row.get("player_name", "").strip()
        if name and name.casefold() not in player_by_name:
            missing_players.add(name)

    players_created = 0
    for name in sorted(missing_players):
        slug = unique_player_slug(league.id, name)
        new_player = create_player(league.id, name, slug)
        db.session.flush()
        player_by_name[name.casefold()] = new_player
        players_created += 1

    errors: list[str] = []
    queued: list[dict] = []
    skipped = 0

    for row_num, row in enumerate(csv.DictReader(lines), start=2):
        event_id = row.get("id", "").strip()
        if event_id and event_id in existing_legacy_ids:
            skipped += 1
            continue

        raw_type = row.get("event_type", "").strip()
        canonical = canonical_event_type(raw_type)
        if canonical not in CANONICAL_EVENT_TYPES:
            errors.append(f"Row {row_num}: unknown event_type '{raw_type}'")
            continue

        try:
            amount_cents = int(row.get("amount_cents", "0"))
        except ValueError:
            errors.append(f"Row {row_num}: invalid amount_cents '{row.get('amount_cents')}'")
            continue

        session_ref = row.get("session_id", "").strip()
        session = session_by_ref.get(session_ref)
        if session is None:
            errors.append(f"Row {row_num}: session '{session_ref}' not found in this league")
            continue

        player_name = row.get("player_name", "").strip()
        player_id = None
        if canonical not in {"note", "session_open", "session_close"}:
            player = player_by_name.get(player_name.casefold())
            if player is None:
                errors.append(f"Row {row_num}: player '{player_name}' not found in this league")
                continue
            player_id = player.id

        queued.append({
            "session_id": session.id,
            "event_type": canonical,
            "amount_cents": amount_cents,
            "player_id": player_id,
            "note": row.get("note", "").strip() or None,
            "legacy_event_id": event_id or None,
            "legacy_player_name": player_name or None,
        })

    if errors:
        for msg in errors[:5]:
            flash(msg, "error")
        if len(errors) > 5:
            flash(f"… and {len(errors) - 5} more error(s). Nothing was imported.", "error")
        return redirect(url_for("leagues.ledger", **league_url_values(league)))

    for ev in queued:
        append_ledger_event(
            league.id,
            ev["session_id"],
            ev["event_type"],
            ev["amount_cents"],
            current_user_id() or "",
            player_id=ev["player_id"],
            note=ev["note"],
            legacy_event_id=ev["legacy_event_id"],
            legacy_player_name=ev["legacy_player_name"],
        )

    db.session.commit()
    s_count = f"{len(queued)} event{'s' if len(queued) != 1 else ''}"
    s_skip = f"{skipped} duplicate{'s' if skipped != 1 else ''}"
    parts = [f"Imported {s_count}", f"skipped {s_skip}"]
    if sessions_created:
        parts.append(f"created {sessions_created} session{'s' if sessions_created != 1 else ''}")
    if players_created:
        parts.append(f"created {players_created} player{'s' if players_created != 1 else ''}")
    flash(", ".join(parts) + ".", "success")
    return redirect(url_for("leagues.ledger", **league_url_values(league)))
