#!/usr/bin/env python3
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import extract, or_
from sqlalchemy.exc import IntegrityError

from boker.auth import (
    current_user_id,
    generate_reset_token,
    hash_password,
    normalize_email,
    site_admin_required,
)
from boker.db import db
from boker.db_models import LedgerEvent, League, LeagueMembership, Player, PokerSession, User, utc_now
from boker.league_repositories import delete_league, transfer_league_ownership
from boker.utils import slugify


internal_bp = Blueprint("internal", __name__, url_prefix="/internal")


def _current_admin() -> User:
    return User.query.filter_by(id=current_user_id()).one()


def _user_or_404(user_id: str) -> User:
    return User.query.filter_by(id=user_id).one_or_404()


def _league_or_404(league_id: str) -> League:
    return League.query.filter_by(id=league_id).one_or_404()


def _owner_for_league(league_id: str) -> User | None:
    row = (
        db.session.query(User)
        .join(LeagueMembership, LeagueMembership.user_id == User.id)
        .filter(
            LeagueMembership.league_id == league_id,
            LeagueMembership.role == "owner",
            LeagueMembership.disabled_at.is_(None),
        )
        .one_or_none()
    )
    return row


def _temporary_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


_CASH_IN_TYPES = ("buyin", "debt_repayment", "front_collected")
_PAGE_SIZE = 50


def _page_number() -> int:
    try:
        return max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        return 1


def _paginate(query, page: int, per_page: int = _PAGE_SIZE) -> dict:
    total = query.order_by(None).count()
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return {
        "items": items,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_page": page - 1,
        "next_page": page + 1,
        "start": ((page - 1) * per_page + 1) if total else 0,
        "end": min(page * per_page, total),
    }


def _site_stats() -> dict:
    now = datetime.now(timezone.utc)
    today = now.date()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    week_ago_date = week_ago.date()
    month_ago = now - timedelta(days=30)

    cash_in_cents = (
        db.session.query(db.func.coalesce(db.func.sum(LedgerEvent.amount_cents), 0))
        .filter(LedgerEvent.voided_at.is_(None), LedgerEvent.event_type.in_(_CASH_IN_TYPES))
        .scalar()
    )
    cash_out_cents = (
        db.session.query(db.func.coalesce(db.func.sum(LedgerEvent.amount_cents), 0))
        .filter(LedgerEvent.voided_at.is_(None), LedgerEvent.event_type == "paid_out")
        .scalar()
    )

    # avg distinct players per session (via buyin events)
    session_player_counts = (
        db.session.query(
            LedgerEvent.session_id,
            db.func.count(db.func.distinct(LedgerEvent.player_id)).label("n"),
        )
        .filter(LedgerEvent.event_type == "buyin", LedgerEvent.voided_at.is_(None))
        .group_by(LedgerEvent.session_id)
        .subquery()
    )
    avg_players = db.session.query(
        db.func.coalesce(db.func.avg(session_player_counts.c.n), 0)
    ).scalar()

    users_in_leagues = (
        db.session.query(db.func.count(db.func.distinct(LeagueMembership.user_id)))
        .filter(LeagueMembership.disabled_at.is_(None))
        .scalar()
    )
    leagues_with_sessions = (
        db.session.query(db.func.count(db.func.distinct(PokerSession.league_id)))
        .scalar()
    )
    leagues_active_7d = (
        db.session.query(db.func.count(db.func.distinct(PokerSession.league_id)))
        .filter(PokerSession.session_date >= week_ago_date)
        .scalar()
    )
    sessions_with_events = (
        db.session.query(db.func.count(db.func.distinct(LedgerEvent.session_id)))
        .filter(LedgerEvent.voided_at.is_(None))
        .scalar()
    )

    session_count = PokerSession.query.count()
    active_league_count = League.query.filter_by(archived_at=None).count()
    active_users_24h = User.query.filter(User.last_login_at >= day_ago).count()
    active_users_7d = User.query.filter(User.last_login_at >= week_ago).count()
    active_users_30d = User.query.filter(User.last_login_at >= month_ago).count()
    returning_users_7d = User.query.filter(User.created_at < week_ago, User.last_login_at >= week_ago).count()
    returning_users_30d = User.query.filter(User.created_at < month_ago, User.last_login_at >= month_ago).count()
    total_users = User.query.count()
    voided_events = LedgerEvent.query.filter(LedgerEvent.voided_at.is_not(None)).count()
    ledger_events = LedgerEvent.query.filter_by(voided_at=None).count()

    return {
        "users": total_users,
        "active_users": User.query.filter_by(disabled_at=None).count(),
        "disabled_users": User.query.filter(User.disabled_at.is_not(None)).count(),
        "verified_users": User.query.filter(User.email_verified_at.is_not(None)).count(),
        "unverified_users": User.query.filter(User.email_verified_at.is_(None)).count(),
        "users_in_leagues": int(users_in_leagues or 0),
        "orphan_users": total_users - int(users_in_leagues or 0),
        "site_admins": User.query.filter_by(is_site_admin=True, disabled_at=None).count(),
        "new_users_24h": User.query.filter(User.created_at >= day_ago).count(),
        "new_users_7d": User.query.filter(User.created_at >= week_ago).count(),
        "active_users_24h": active_users_24h,
        "active_users_7d": active_users_7d,
        "active_users_30d": active_users_30d,
        "returning_users_7d": returning_users_7d,
        "returning_users_30d": returning_users_30d,
        "leagues": League.query.count(),
        "active_leagues": active_league_count,
        "archived_leagues": League.query.filter(League.archived_at.is_not(None)).count(),
        "public_leagues": League.query.filter_by(visibility="public", archived_at=None).count(),
        "leagues_with_sessions": int(leagues_with_sessions or 0),
        "leagues_without_sessions": max(active_league_count - int(leagues_with_sessions or 0), 0),
        "leagues_active_7d": int(leagues_active_7d or 0),
        "sessions": session_count,
        "open_sessions": PokerSession.query.filter_by(status="open").count(),
        "sessions_24h": PokerSession.query.filter(PokerSession.session_date == today).count(),
        "sessions_7d": PokerSession.query.filter(PokerSession.session_date >= week_ago_date).count(),
        "sessions_without_events": max(session_count - int(sessions_with_events or 0), 0),
        "ledger_events": ledger_events,
        "ledger_events_24h": LedgerEvent.query.filter(LedgerEvent.created_at >= day_ago).count(),
        "ledger_events_7d": LedgerEvent.query.filter(LedgerEvent.created_at >= week_ago).count(),
        "voided_events": voided_events,
        "void_rate": round((voided_events / (ledger_events + voided_events)) * 100, 1) if ledger_events or voided_events else 0,
        "cash_in_cents": int(cash_in_cents or 0),
        "cash_out_cents": int(cash_out_cents or 0),
        "avg_cash_in_per_session_cents": int((cash_in_cents or 0) / session_count) if session_count else 0,
        "avg_sessions_per_active_league": round(session_count / active_league_count, 1) if active_league_count else 0,
        "avg_players_per_session": round(float(avg_players or 0), 1),
    }


def _top_leagues(limit: int = 8):
    rows = (
        db.session.query(League, db.func.count(PokerSession.id).label("n"))
        .outerjoin(PokerSession, PokerSession.league_id == League.id)
        .filter(League.archived_at.is_(None))
        .group_by(League.id)
        .order_by(db.func.count(PokerSession.id).desc())
        .limit(limit)
        .all()
    )
    return [(league, count) for league, count in rows]


def _session_weekday_expression(dialect_name: str | None = None):
    dialect_name = dialect_name or db.session.get_bind().dialect.name
    if dialect_name == "sqlite":
        return db.func.strftime("%w", PokerSession.session_date)
    return extract("dow", PokerSession.session_date)


def _sessions_by_weekday() -> dict:
    rows = (
        db.session.query(
            _session_weekday_expression().label("dow"),
            db.func.count(PokerSession.id).label("cnt"),
        )
        .group_by("dow")
        .all()
    )
    counts = {str(i): 0 for i in range(7)}
    for row in rows:
        counts[str(int(row.dow))] = row.cnt
    return {
        "labels": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "data": [counts[str(i)] for i in range(7)],
    }


def _growth_data(weeks: int = 8) -> dict:
    now = datetime.now(timezone.utc)
    labels, user_signups, session_counts, league_counts = [], [], [], []
    for i in range(weeks - 1, -1, -1):
        start = now - timedelta(weeks=i + 1)
        end = now - timedelta(weeks=i)
        start_date = start.date()
        end_date = end.date()
        labels.append(start.strftime("%b %-d"))
        user_signups.append(User.query.filter(User.created_at >= start, User.created_at < end).count())
        session_counts.append(
            PokerSession.query.filter(
                PokerSession.session_date >= start_date,
                PokerSession.session_date < end_date,
            ).count()
        )
        league_counts.append(League.query.filter(League.created_at >= start, League.created_at < end).count())
    return {
        "labels": labels,
        "user_signups": user_signups,
        "session_counts": session_counts,
        "league_counts": league_counts,
    }


def _trend_delta(current: int | float, previous: int | float) -> dict:
    if previous == 0:
        pct = None if current else 0
    else:
        pct = round(((current - previous) / previous) * 100, 1)
    direction = "flat"
    if current > previous:
        direction = "up"
    elif current < previous:
        direction = "down"
    return {"current": current, "previous": previous, "pct": pct, "direction": direction}


def _trend_cards(growth: dict) -> list[dict]:
    labels = growth["labels"]
    user_series = growth["user_signups"]
    session_series = growth["session_counts"]
    league_series = growth["league_counts"]
    current_start = datetime.now(timezone.utc) - timedelta(days=7)
    previous_start = current_start - timedelta(days=7)

    active_current = User.query.filter(User.last_login_at >= current_start).count()
    active_previous = User.query.filter(
        User.last_login_at >= previous_start,
        User.last_login_at < current_start,
    ).count()
    event_current = LedgerEvent.query.filter(
        LedgerEvent.voided_at.is_(None),
        LedgerEvent.created_at >= current_start,
    ).count()
    event_previous = LedgerEvent.query.filter(
        LedgerEvent.voided_at.is_(None),
        LedgerEvent.created_at >= previous_start,
        LedgerEvent.created_at < current_start,
    ).count()

    return [
        {
            "key": "signups",
            "label": "New users",
            "value": user_series[-1] if user_series else 0,
            "delta": _trend_delta(user_series[-1] if user_series else 0, user_series[-2] if len(user_series) > 1 else 0),
            "labels": labels,
            "series": user_series,
        },
        {
            "key": "active",
            "label": "Active users",
            "value": active_current,
            "delta": _trend_delta(active_current, active_previous),
            "labels": ["Previous", "Current"],
            "series": [active_previous, active_current],
        },
        {
            "key": "sessions",
            "label": "Sessions",
            "value": session_series[-1] if session_series else 0,
            "delta": _trend_delta(session_series[-1] if session_series else 0, session_series[-2] if len(session_series) > 1 else 0),
            "labels": labels,
            "series": session_series,
        },
        {
            "key": "ledger",
            "label": "Ledger records",
            "value": event_current,
            "delta": _trend_delta(event_current, event_previous),
            "labels": ["Previous", "Current"],
            "series": [event_previous, event_current],
        },
        {
            "key": "leagues",
            "label": "New leagues",
            "value": league_series[-1] if league_series else 0,
            "delta": _trend_delta(league_series[-1] if league_series else 0, league_series[-2] if len(league_series) > 1 else 0),
            "labels": labels,
            "series": league_series,
        },
    ]


@internal_bp.get("/")
@site_admin_required
def dashboard():
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    recent_leagues = League.query.order_by(League.created_at.desc()).limit(8).all()
    top_leagues = _top_leagues()
    owners = {league.id: _owner_for_league(league.id) for league in recent_leagues + [l for l, _ in top_leagues]}
    growth = _growth_data()
    return render_template(
        "internal_dashboard.html",
        admin_user=_current_admin(),
        stats=_site_stats(),
        growth=growth,
        trend_cards=_trend_cards(growth),
        weekday_data=_sessions_by_weekday(),
        top_leagues=top_leagues,
        recent_users=recent_users,
        recent_leagues=recent_leagues,
        owners=owners,
    )


@internal_bp.get("/users")
@site_admin_required
def users():
    q = request.args.get("q", "").strip()
    page = _page_number()
    query = User.query
    if q:
        query = query.filter(User.email.ilike(f"%{normalize_email(q)}%"))
    pagination = _paginate(query.order_by(User.created_at.desc()), page)
    return render_template("internal_users.html", users=pagination["items"], pagination=pagination, q=q)


@internal_bp.get("/users/<user_id>")
@site_admin_required
def user_detail(user_id: str):
    user = _user_or_404(user_id)
    memberships = (
        db.session.query(LeagueMembership, League)
        .join(League, League.id == LeagueMembership.league_id)
        .filter(LeagueMembership.user_id == user.id)
        .order_by(LeagueMembership.created_at.desc())
        .all()
    )
    owned_leagues = League.query.filter_by(created_by_user_id=user.id).order_by(League.created_at.desc()).all()
    event_count = LedgerEvent.query.filter_by(created_by_user_id=user.id).count()
    return render_template(
        "internal_user_detail.html",
        user=user,
        memberships=memberships,
        owned_leagues=owned_leagues,
        event_count=event_count,
        current_admin_id=current_user_id(),
    )


@internal_bp.post("/users/<user_id>/email")
@site_admin_required
def update_user_email(user_id: str):
    user = _user_or_404(user_id)
    new_email = normalize_email(request.form.get("email", ""))

    if not new_email or "@" not in new_email:
        flash("Enter a valid email address.", "error")
        return redirect(url_for("internal.user_detail", user_id=user.id))

    existing = User.query.filter(User.email == new_email, User.id != user.id).one_or_none()
    if existing:
        flash("That email is already in use.", "error")
        return redirect(url_for("internal.user_detail", user_id=user.id))

    user.email = new_email
    db.session.commit()
    flash("User email updated.", "success")
    return redirect(url_for("internal.user_detail", user_id=user.id))


@internal_bp.post("/users/<user_id>/password-reset")
@site_admin_required
def send_user_password_reset(user_id: str):
    user = _user_or_404(user_id)
    if user.disabled_at is not None:
        flash("Disabled users cannot receive password resets.", "error")
        return redirect(url_for("internal.user_detail", user_id=user.id))

    from boker.emails import send_password_reset

    token = generate_reset_token(user.id)
    base_url = current_app.config.get("APP_BASE_URL", "").rstrip("/")
    reset_url = f"{base_url}{url_for('account.reset_password', token=token)}"
    try:
        send_password_reset(user.email, reset_url)
        flash("Password reset email sent.", "success")
    except Exception:
        flash("Password reset email could not be sent. Check mail configuration.", "error")
    return redirect(url_for("internal.user_detail", user_id=user.id))


@internal_bp.post("/users/<user_id>/temporary-password")
@site_admin_required
def create_user_temporary_password(user_id: str):
    user = _user_or_404(user_id)
    if user.disabled_at is not None:
        flash("Disabled users cannot receive temporary passwords.", "error")
        return redirect(url_for("internal.user_detail", user_id=user.id))

    from boker.emails import send_temporary_password

    temporary_password = _temporary_password()
    user.password_hash = hash_password(temporary_password)
    db.session.commit()
    try:
        send_temporary_password(user.email, temporary_password)
        flash("Temporary password created and emailed.", "success")
    except Exception:
        flash(f"Temporary password created but email failed: {temporary_password}", "error")
    return redirect(url_for("internal.user_detail", user_id=user.id))


@internal_bp.post("/users/<user_id>/disable")
@site_admin_required
def disable_user(user_id: str):
    user = _user_or_404(user_id)
    if user.id == current_user_id():
        flash("You cannot disable your own admin account.", "error")
    elif user.disabled_at is None:
        user.disabled_at = utc_now()
        db.session.commit()
        flash("User disabled.", "success")
    return redirect(url_for("internal.user_detail", user_id=user.id))


@internal_bp.post("/users/<user_id>/restore")
@site_admin_required
def restore_user(user_id: str):
    user = _user_or_404(user_id)
    user.disabled_at = None
    db.session.commit()
    flash("User restored.", "success")
    return redirect(url_for("internal.user_detail", user_id=user.id))


@internal_bp.post("/users/<user_id>/delete")
@site_admin_required
def delete_user(user_id: str):
    user = _user_or_404(user_id)
    confirm = request.form.get("confirm", "").strip()
    if user.id == current_user_id():
        flash("You cannot delete your own admin account.", "error")
        return redirect(url_for("internal.user_detail", user_id=user.id))
    if confirm != "DELETE":
        flash("Confirmation text did not match.", "error")
        return redirect(url_for("internal.user_detail", user_id=user.id))

    owned_leagues = League.query.filter_by(created_by_user_id=user.id).count()
    if owned_leagues:
        flash("Transfer or delete this user's owned leagues before deleting the account.", "error")
        return redirect(url_for("internal.user_detail", user_id=user.id))

    LeagueMembership.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    try:
        db.session.delete(user)
        db.session.commit()
        flash("User deleted.", "success")
        return redirect(url_for("internal.users"))
    except IntegrityError:
        db.session.rollback()
        flash("User has audit history and cannot be deleted safely. Disable the account instead.", "error")
        return redirect(url_for("internal.user_detail", user_id=user.id))


@internal_bp.get("/leagues")
@site_admin_required
def leagues():
    q = request.args.get("q", "").strip()
    page = _page_number()
    query = db.session.query(League)
    if q:
        term = f"%{q.strip()}%"
        query = (
            query.outerjoin(LeagueMembership, LeagueMembership.league_id == League.id)
            .outerjoin(User, User.id == LeagueMembership.user_id)
            .filter(
                or_(
                    League.name.ilike(term),
                    League.slug.ilike(term),
                    User.email.ilike(term),
                )
            )
            .distinct()
        )
    pagination = _paginate(query.order_by(League.created_at.desc()), page)
    leagues = pagination["items"]
    owners = {league.id: _owner_for_league(league.id) for league in leagues}
    return render_template("internal_leagues.html", leagues=leagues, owners=owners, pagination=pagination, q=q)


@internal_bp.get("/leagues/<league_id>")
@site_admin_required
def league_detail(league_id: str):
    league = _league_or_404(league_id)
    members = (
        db.session.query(LeagueMembership, User)
        .join(User, User.id == LeagueMembership.user_id)
        .filter(LeagueMembership.league_id == league.id)
        .order_by(LeagueMembership.created_at.asc())
        .all()
    )
    stats = {
        "members": len([m for m, _u in members if m.disabled_at is None]),
        "players": Player.query.filter_by(league_id=league.id).count(),
        "sessions": PokerSession.query.filter_by(league_id=league.id).count(),
        "events": LedgerEvent.query.filter_by(league_id=league.id).count(),
        "voided_events": LedgerEvent.query.filter(LedgerEvent.league_id == league.id, LedgerEvent.voided_at.is_not(None)).count(),
    }
    owner = _owner_for_league(league.id)
    return render_template("internal_league_detail.html", league=league, owner=owner, members=members, stats=stats)


@internal_bp.post("/leagues/<league_id>/archive")
@site_admin_required
def archive_league(league_id: str):
    league = _league_or_404(league_id)
    league.archived_at = utc_now()
    db.session.commit()
    flash("League archived.", "success")
    return redirect(url_for("internal.league_detail", league_id=league.id))


@internal_bp.post("/leagues/<league_id>/settings")
@site_admin_required
def update_league_settings(league_id: str):
    league = _league_or_404(league_id)
    raw_eligible = request.form.get("eligible_min_sessions", "3").strip()
    raw_break_even = request.form.get("break_even_dollars", "1.00").strip()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    visibility = request.form.get("visibility", "private").strip()

    try:
        eligible_min = int(raw_eligible)
        break_even_cents = round(float(raw_break_even) * 100)
    except (ValueError, TypeError):
        flash("Eligible sessions and break-even threshold must be valid numbers.", "error")
        return redirect(url_for("internal.league_detail", league_id=league.id))

    if len(name) < 2:
        flash("League name must be at least 2 characters.", "error")
    elif visibility not in ("private", "public"):
        flash("Invalid visibility value.", "error")
    elif eligible_min < 1 or eligible_min > 100:
        flash("Eligible minimum must be between 1 and 100.", "error")
    elif break_even_cents < 0 or break_even_cents > 10000:
        flash("Break-even threshold must be between $0.00 and $100.00.", "error")
    else:
        league.name = name
        league.slug = slugify(name)
        league.description = description or None
        league.visibility = visibility
        league.eligible_min_sessions = eligible_min
        league.break_even_cents = break_even_cents
        db.session.commit()
        flash("League settings updated.", "success")

    return redirect(url_for("internal.league_detail", league_id=league.id))


@internal_bp.post("/leagues/<league_id>/restore")
@site_admin_required
def restore_league(league_id: str):
    league = _league_or_404(league_id)
    league.archived_at = None
    db.session.commit()
    flash("League restored.", "success")
    return redirect(url_for("internal.league_detail", league_id=league.id))


@internal_bp.post("/leagues/<league_id>/transfer")
@site_admin_required
def transfer_league_owner(league_id: str):
    league = _league_or_404(league_id)
    new_owner_email = normalize_email(request.form.get("new_owner_email", ""))
    new_owner = User.query.filter_by(email=new_owner_email, disabled_at=None).one_or_none()
    current_owner = _owner_for_league(league.id)

    if current_owner is None:
        flash("Current owner could not be found.", "error")
    elif new_owner is None:
        flash("New owner must be an active user.", "error")
    else:
        membership = LeagueMembership.query.filter_by(league_id=league.id, user_id=new_owner.id).one_or_none()
        if membership is None:
            membership = LeagueMembership(league_id=league.id, user_id=new_owner.id, role="manager")
            db.session.add(membership)
            db.session.flush()
        membership.disabled_at = None
        result = transfer_league_ownership(league, current_owner.id, new_owner.id)
        if result is None:
            flash("Ownership transfer failed.", "error")
        else:
            db.session.commit()
            flash("League ownership transferred.", "success")
            return redirect(url_for("internal.league_detail", league_id=league.id))

    db.session.rollback()
    return redirect(url_for("internal.league_detail", league_id=league.id))


@internal_bp.post("/leagues/<league_id>/delete")
@site_admin_required
def delete_internal_league(league_id: str):
    league = _league_or_404(league_id)
    confirm = request.form.get("confirm", "").strip()
    if confirm != "DELETE":
        flash("Confirmation text did not match.", "error")
        return redirect(url_for("internal.league_detail", league_id=league.id))

    delete_league(league)
    db.session.commit()
    flash("League deleted.", "success")
    return redirect(url_for("internal.leagues"))
