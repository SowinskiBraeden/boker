#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..auth import (
    current_user_id,
    generate_reset_token,
    hash_password,
    normalize_email,
    site_admin_required,
)
from ..db import db

site_admin_bp = Blueprint("site_admin", __name__, url_prefix="/admin")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@site_admin_bp.get("/")
def index():
    return redirect(url_for("site_admin.dashboard"))


@site_admin_bp.get("/dashboard")
@site_admin_required
def dashboard():
    from ..db_models import League, LedgerEvent, LeagueMembership, PokerSession, User

    now = utc_now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    total_users = db.session.query(db.func.count(User.id)).scalar() or 0
    active_users = db.session.query(db.func.count(User.id)).filter(User.disabled_at.is_(None)).scalar() or 0
    disabled_users = total_users - active_users
    new_users_7d = db.session.query(db.func.count(User.id)).filter(User.created_at >= week_ago).scalar() or 0
    new_users_30d = db.session.query(db.func.count(User.id)).filter(User.created_at >= month_ago).scalar() or 0
    admin_count = db.session.query(db.func.count(User.id)).filter(User.is_site_admin.is_(True)).scalar() or 0

    dau = db.session.query(db.func.count(User.id)).filter(User.last_login_at >= day_ago).scalar() or 0
    wau = db.session.query(db.func.count(User.id)).filter(User.last_login_at >= week_ago).scalar() or 0
    mau = db.session.query(db.func.count(User.id)).filter(User.last_login_at >= month_ago).scalar() or 0

    total_leagues = db.session.query(db.func.count(League.id)).scalar() or 0
    active_leagues = db.session.query(db.func.count(League.id)).filter(League.archived_at.is_(None)).scalar() or 0
    public_leagues = db.session.query(db.func.count(League.id)).filter(
        League.visibility == "public", League.archived_at.is_(None)
    ).scalar() or 0
    new_leagues_30d = db.session.query(db.func.count(League.id)).filter(League.created_at >= month_ago).scalar() or 0

    total_sessions = db.session.query(db.func.count(PokerSession.id)).scalar() or 0
    open_sessions = db.session.query(db.func.count(PokerSession.id)).filter(PokerSession.status == "open").scalar() or 0

    total_events = db.session.query(db.func.count(LedgerEvent.id)).filter(LedgerEvent.voided_at.is_(None)).scalar() or 0

    league_session_rows = db.session.query(
        PokerSession.league_id, db.func.count(PokerSession.id)
    ).group_by(PokerSession.league_id).all()
    avg_sessions_per_league = round(
        sum(r[1] for r in league_session_rows) / len(league_session_rows), 1
    ) if league_session_rows else 0

    league_buyin_rows = db.session.query(
        LedgerEvent.league_id, db.func.sum(LedgerEvent.amount_cents)
    ).filter(
        LedgerEvent.event_type == "buyin",
        LedgerEvent.voided_at.is_(None),
    ).group_by(LedgerEvent.league_id).all()
    avg_buyin_cents = int(
        sum(r[1] for r in league_buyin_rows) / len(league_buyin_rows)
    ) if league_buyin_rows else 0

    today = now.date()
    chart_days = [today - timedelta(days=i) for i in range(29, -1, -1)]
    chart_labels = [d.strftime("%b %d") for d in chart_days]
    chart_iso = [d.isoformat() for d in chart_days]

    signup_raw = db.session.query(
        db.func.date(User.created_at),
        db.func.count(User.id),
    ).filter(User.created_at >= month_ago).group_by(db.func.date(User.created_at)).all()
    signup_by_day = {
        (r[0].isoformat() if hasattr(r[0], "isoformat") else r[0]): r[1]
        for r in signup_raw
    }
    chart_signups = [signup_by_day.get(d, 0) for d in chart_iso]

    login_raw = db.session.query(
        db.func.date(User.last_login_at),
        db.func.count(User.id),
    ).filter(User.last_login_at >= month_ago).group_by(db.func.date(User.last_login_at)).all()
    login_by_day = {
        (r[0].isoformat() if hasattr(r[0], "isoformat") else r[0]): r[1]
        for r in login_raw
    }
    chart_logins = [login_by_day.get(d, 0) for d in chart_iso]

    session_raw = db.session.query(
        PokerSession.session_date,
        db.func.count(PokerSession.id),
    ).filter(PokerSession.session_date >= chart_days[0]).group_by(PokerSession.session_date).all()
    session_by_day = {
        (r[0].isoformat() if hasattr(r[0], "isoformat") else r[0]): r[1]
        for r in session_raw
    }
    chart_sessions = [session_by_day.get(d, 0) for d in chart_iso]

    chart_data = json.dumps({
        "labels": chart_labels,
        "signups": chart_signups,
        "logins": chart_logins,
        "sessions": chart_sessions,
    })

    recent_users = (
        db.session.query(User)
        .order_by(User.created_at.desc())
        .limit(10)
        .all()
    )
    recent_leagues = (
        db.session.query(League)
        .order_by(League.created_at.desc())
        .limit(10)
        .all()
    )
    league_owner_ids = {league.created_by_user_id for league in recent_leagues}
    owners_by_id = {
        u.id: u
        for u in db.session.query(User).filter(User.id.in_(league_owner_ids)).all()
    } if league_owner_ids else {}

    stats = {
        "total_users": total_users,
        "active_users": active_users,
        "disabled_users": disabled_users,
        "new_users_7d": new_users_7d,
        "new_users_30d": new_users_30d,
        "admin_count": admin_count,
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "total_leagues": total_leagues,
        "active_leagues": active_leagues,
        "public_leagues": public_leagues,
        "new_leagues_30d": new_leagues_30d,
        "total_sessions": total_sessions,
        "open_sessions": open_sessions,
        "total_events": total_events,
        "avg_sessions_per_league": avg_sessions_per_league,
        "avg_buyin_cents": avg_buyin_cents,
    }

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_users=recent_users,
        recent_leagues=recent_leagues,
        owners_by_id=owners_by_id,
        chart_data=chart_data,
    )


@site_admin_bp.get("/users")
@site_admin_required
def users():
    from ..db_models import League, LeagueMembership, User

    search = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50

    query = db.session.query(User)
    if search:
        query = query.filter(User.email.ilike(f"%{search}%"))
    query = query.order_by(User.created_at.desc())

    total = query.count()
    user_list = query.offset((page - 1) * per_page).limit(per_page).all()

    user_ids = [u.id for u in user_list]
    league_counts = {}
    if user_ids:
        rows = (
            db.session.query(
                LeagueMembership.user_id,
                db.func.count(LeagueMembership.id),
            )
            .filter(LeagueMembership.user_id.in_(user_ids))
            .group_by(LeagueMembership.user_id)
            .all()
        )
        league_counts = {row[0]: row[1] for row in rows}

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "admin/users.html",
        users=user_list,
        league_counts=league_counts,
        search=search,
        page=page,
        total=total,
        total_pages=total_pages,
    )


@site_admin_bp.get("/users/<user_id>")
@site_admin_required
def user_detail(user_id: str):
    from flask import current_app

    from ..db_models import League, LeagueMembership, User

    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("site_admin.users"))

    memberships = (
        db.session.query(LeagueMembership, League)
        .join(League, League.id == LeagueMembership.league_id)
        .filter(LeagueMembership.user_id == user_id)
        .order_by(LeagueMembership.created_at.desc())
        .all()
    )

    reset_url = None
    if request.args.get("show_reset") == "1":
        token = generate_reset_token(user.id)
        base_url = current_app.config.get("APP_BASE_URL", "").rstrip("/")
        reset_url = f"{base_url}{url_for('account.reset_password', token=token)}"

    return render_template(
        "admin/user_detail.html",
        user=user,
        memberships=memberships,
        reset_url=reset_url,
        viewing_self=user_id == current_user_id(),
    )


@site_admin_bp.post("/users/<user_id>/send-reset")
@site_admin_required
def send_reset(user_id: str):
    from flask import current_app

    from ..db_models import User
    from ..emails import send_password_reset

    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("site_admin.users"))

    if user.disabled_at is not None:
        flash("Cannot send a reset link to a disabled account.", "error")
        return redirect(url_for("site_admin.user_detail", user_id=user_id))

    token = generate_reset_token(user.id)
    base_url = current_app.config.get("APP_BASE_URL", "").rstrip("/")
    reset_url = f"{base_url}{url_for('account.reset_password', token=token)}"

    email_sent = False
    try:
        send_password_reset(user.email, reset_url)
        email_sent = True
    except Exception:
        pass

    if email_sent:
        flash(f"Password reset email sent to {user.email}.", "success")
    else:
        flash("Email not sent (mail not configured). Copy the link below.", "error")

    return redirect(url_for("site_admin.user_detail", user_id=user_id, show_reset="1"))


@site_admin_bp.post("/users/<user_id>/disable")
@site_admin_required
def disable_user(user_id: str):
    from ..db_models import User

    if user_id == current_user_id():
        flash("You cannot disable your own account.", "error")
        return redirect(url_for("site_admin.user_detail", user_id=user_id))

    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("site_admin.users"))

    if user.disabled_at is None:
        user.disabled_at = utc_now()
        db.session.commit()
        flash(f"{user.email} has been disabled.", "success")
    else:
        flash("Account is already disabled.", "error")

    return redirect(url_for("site_admin.user_detail", user_id=user_id))


@site_admin_bp.post("/users/<user_id>/enable")
@site_admin_required
def enable_user(user_id: str):
    from ..db_models import User

    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("site_admin.users"))

    if user.disabled_at is not None:
        user.disabled_at = None
        db.session.commit()
        flash(f"{user.email} has been re-enabled.", "success")
    else:
        flash("Account is not disabled.", "error")

    return redirect(url_for("site_admin.user_detail", user_id=user_id))


@site_admin_bp.post("/users/<user_id>/grant-admin")
@site_admin_required
def grant_admin(user_id: str):
    from ..db_models import User

    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("site_admin.users"))

    user.is_site_admin = True
    db.session.commit()
    flash(f"{user.email} is now a site admin.", "success")
    return redirect(url_for("site_admin.user_detail", user_id=user_id))


@site_admin_bp.post("/users/<user_id>/revoke-admin")
@site_admin_required
def revoke_admin(user_id: str):
    from ..db_models import User

    if user_id == current_user_id():
        flash("You cannot revoke your own admin access.", "error")
        return redirect(url_for("site_admin.user_detail", user_id=user_id))

    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("site_admin.users"))

    user.is_site_admin = False
    db.session.commit()
    flash(f"Admin access removed from {user.email}.", "success")
    return redirect(url_for("site_admin.user_detail", user_id=user_id))


@site_admin_bp.post("/users/<user_id>/reset-password")
@site_admin_required
def admin_reset_password(user_id: str):
    from ..db_models import User

    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("site_admin.users"))

    new_password = request.form.get("new_password", "")
    if len(new_password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return redirect(url_for("site_admin.user_detail", user_id=user_id))

    user.password_hash = hash_password(new_password)
    db.session.commit()
    flash(f"Password updated for {user.email}.", "success")
    return redirect(url_for("site_admin.user_detail", user_id=user_id))


@site_admin_bp.get("/leagues")
@site_admin_required
def leagues():
    from ..db_models import League, LeagueMembership, PokerSession, User

    search = request.args.get("q", "").strip()
    visibility = request.args.get("visibility", "").strip()
    show_archived = request.args.get("archived", "0") == "1"
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50

    query = (
        db.session.query(League)
        .outerjoin(User, User.id == League.created_by_user_id)
    )
    if search:
        query = query.filter(
            db.or_(
                League.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
            )
        )
    if visibility in ("public", "private"):
        query = query.filter(League.visibility == visibility)
    if not show_archived:
        query = query.filter(League.archived_at.is_(None))
    query = query.order_by(League.created_at.desc())

    total = query.count()
    league_list = query.offset((page - 1) * per_page).limit(per_page).all()

    league_ids = [lg.id for lg in league_list]
    owner_ids = [lg.created_by_user_id for lg in league_list]

    owners_by_id = {}
    if owner_ids:
        owners_by_id = {
            u.id: u
            for u in db.session.query(User).filter(User.id.in_(owner_ids)).all()
        }

    member_counts = {}
    session_counts = {}
    if league_ids:
        for row in (
            db.session.query(LeagueMembership.league_id, db.func.count(LeagueMembership.id))
            .filter(LeagueMembership.league_id.in_(league_ids))
            .group_by(LeagueMembership.league_id)
            .all()
        ):
            member_counts[row[0]] = row[1]

        for row in (
            db.session.query(PokerSession.league_id, db.func.count(PokerSession.id))
            .filter(PokerSession.league_id.in_(league_ids))
            .group_by(PokerSession.league_id)
            .all()
        ):
            session_counts[row[0]] = row[1]

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "admin/leagues.html",
        leagues=league_list,
        owners_by_id=owners_by_id,
        member_counts=member_counts,
        session_counts=session_counts,
        search=search,
        visibility=visibility,
        show_archived=show_archived,
        page=page,
        total=total,
        total_pages=total_pages,
    )


@site_admin_bp.get("/leagues/<league_id>")
@site_admin_required
def league_detail(league_id: str):
    from ..db_models import League, LedgerEvent, LeagueMembership, Player, PokerSession, User

    league = db.session.get(League, league_id)
    if league is None:
        flash("League not found.", "error")
        return redirect(url_for("site_admin.leagues"))

    memberships = (
        db.session.query(LeagueMembership, User)
        .join(User, User.id == LeagueMembership.user_id)
        .filter(LeagueMembership.league_id == league_id)
        .order_by(LeagueMembership.created_at.asc())
        .all()
    )

    owner = db.session.get(User, league.created_by_user_id)

    session_count = db.session.query(db.func.count(PokerSession.id)).filter(
        PokerSession.league_id == league_id
    ).scalar() or 0

    open_sessions = db.session.query(db.func.count(PokerSession.id)).filter(
        PokerSession.league_id == league_id,
        PokerSession.status == "open",
    ).scalar() or 0

    event_count = db.session.query(db.func.count(LedgerEvent.id)).filter(
        LedgerEvent.league_id == league_id,
        LedgerEvent.voided_at.is_(None),
    ).scalar() or 0

    player_count = db.session.query(db.func.count(Player.id)).filter(
        Player.league_id == league_id
    ).scalar() or 0

    return render_template(
        "admin/league_detail.html",
        league=league,
        memberships=memberships,
        owner=owner,
        session_count=session_count,
        open_sessions=open_sessions,
        event_count=event_count,
        player_count=player_count,
    )


@site_admin_bp.post("/leagues/<league_id>/invite")
@site_admin_required
def admin_invite_member(league_id: str):
    from flask import current_app

    from ..auth import generate_invite_token
    from ..db_models import League
    from ..emails import send_league_invite
    from ..repositories.leagues import find_membership, find_user_by_email

    league = db.session.get(League, league_id)
    if league is None:
        flash("League not found.", "error")
        return redirect(url_for("site_admin.leagues"))

    email = normalize_email(request.form.get("email", ""))
    role = request.form.get("role", "manager").strip()

    if not email or "@" not in email:
        flash("Enter a valid email address.", "error")
        return redirect(url_for("site_admin.league_detail", league_id=league_id))

    if role not in ("manager", "viewer"):
        flash("Invalid role.", "error")
        return redirect(url_for("site_admin.league_detail", league_id=league_id))

    existing_user = find_user_by_email(email)
    if existing_user:
        existing_membership = find_membership(league.id, existing_user.id)
        if existing_membership:
            flash(f"{email} is already a member of this league.", "error")
            return redirect(url_for("site_admin.league_detail", league_id=league_id))

    token = generate_invite_token(league.id, email, role, current_user_id() or "")
    base_url = current_app.config.get("APP_BASE_URL", "").rstrip("/")
    invite_url = f"{base_url}{url_for('account.accept_invite', token=token)}"

    try:
        send_league_invite(email, league.name, invite_url, current_user_id() or "")
        flash(f"Invitation sent to {email}.", "success")
    except Exception:
        flash(f"Email not configured. Invite link (copy manually): {invite_url}", "info")

    return redirect(url_for("site_admin.league_detail", league_id=league_id))


@site_admin_bp.post("/leagues/<league_id>/members/<user_id>/remove")
@site_admin_required
def admin_remove_member(league_id: str, user_id: str):
    from ..db_models import League, LeagueMembership
    from ..repositories.leagues import remove_league_member

    league = db.session.get(League, league_id)
    if league is None:
        flash("League not found.", "error")
        return redirect(url_for("site_admin.leagues"))

    membership = LeagueMembership.query.filter_by(
        league_id=league_id,
        user_id=user_id,
        disabled_at=None,
    ).one_or_none()

    if membership is None:
        flash("Member not found.", "error")
        return redirect(url_for("site_admin.league_detail", league_id=league_id))

    if membership.role == "owner":
        flash("Cannot remove the league owner. Transfer ownership first.", "error")
        return redirect(url_for("site_admin.league_detail", league_id=league_id))

    remove_league_member(league_id, user_id)
    db.session.commit()
    flash("Member removed.", "success")
    return redirect(url_for("site_admin.league_detail", league_id=league_id))


@site_admin_bp.post("/leagues/<league_id>/transfer")
@site_admin_required
def admin_transfer_ownership(league_id: str):
    from ..db_models import League
    from ..repositories.leagues import transfer_league_ownership

    league = db.session.get(League, league_id)
    if league is None:
        flash("League not found.", "error")
        return redirect(url_for("site_admin.leagues"))

    new_owner_id = request.form.get("new_owner_user_id", "").strip()
    if not new_owner_id:
        flash("Select a member to transfer ownership to.", "error")
        return redirect(url_for("site_admin.league_detail", league_id=league_id))

    try:
        transfer_league_ownership(league_id, new_owner_id)
        db.session.commit()
        flash("Ownership transferred.", "success")
    except ValueError as exc:
        flash(str(exc), "error")

    return redirect(url_for("site_admin.league_detail", league_id=league_id))
