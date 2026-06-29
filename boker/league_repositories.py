#!/usr/bin/env python3
from __future__ import annotations

import secrets
import string
from datetime import date

from boker.auth import hash_password, normalize_email
from boker.db import db

if db is None:  # pragma: no cover - imported only when DB dependencies exist.
    raise RuntimeError("Database dependencies are not installed.")

from boker.db_models import (  # noqa: E402
    LedgerEvent,
    League,
    LeagueMembership,
    Player,
    PokerSession,
    Season,
    User,
    make_player,
    make_session,
    make_user,
    normalize_lookup,
)
from boker.utils import slugify

PUBLIC_KEY_ALPHABET = string.ascii_lowercase + string.digits


def generate_public_key(length: int = 6) -> str:
    return "".join(secrets.choice(PUBLIC_KEY_ALPHABET) for _ in range(length))


def unique_league_public_key() -> str:
    while True:
        public_key = generate_public_key()
        if League.query.filter_by(public_key=public_key).first() is None:
            return public_key


def create_user(email: str, password: str) -> User:
    user = make_user(normalize_email(email), hash_password(password))
    db.session.add(user)
    return user


def create_league(owner: User, name: str, slug: str, description: str | None = None) -> League:
    league = League(
        name=name.strip(),
        slug=slug.strip().lower(),
        public_key=unique_league_public_key(),
        description=description.strip() if description else None,
        created_by_user_id=owner.id,
    )
    db.session.add(league)
    db.session.flush()

    db.session.add(
        LeagueMembership(
            league_id=league.id,
            user_id=owner.id,
            role="owner",
        )
    )
    return league


def unique_league_slug(name: str, requested_slug: str | None = None) -> str:
    return slugify(requested_slug or name)


def find_user_by_email(email: str) -> User | None:
    return User.query.filter_by(email=normalize_email(email)).one_or_none()


def find_league_by_slug(slug: str) -> League | None:
    return League.query.filter_by(slug=slug.strip().lower(), archived_at=None).one_or_none()


def find_league_by_id(league_id: str) -> League | None:
    return League.query.filter_by(id=league_id, archived_at=None).one_or_none()


def find_league_by_public_key(public_key: str) -> League | None:
    return League.query.filter_by(
        public_key=public_key.strip().lower(),
        archived_at=None,
    ).one_or_none()


def list_public_leagues(name_query: str = "") -> list[League]:
    query = League.query.filter_by(visibility="public", archived_at=None)
    if name_query:
        query = query.filter(League.name.ilike(f"%{name_query}%"))
    return query.order_by(League.name.asc()).all()


def list_leagues_for_user(user_id: str) -> list[tuple[League, LeagueMembership]]:
    return (
        db.session.query(League, LeagueMembership)
        .join(LeagueMembership, LeagueMembership.league_id == League.id)
        .filter(
            LeagueMembership.user_id == user_id,
            LeagueMembership.disabled_at.is_(None),
            League.archived_at.is_(None),
        )
        .order_by(League.name.asc())
        .all()
    )


def league_counts(league_id: str) -> dict[str, int]:
    return {
        "players": Player.query.filter_by(league_id=league_id, status="active").count(),
        "seasons": Season.query.filter_by(league_id=league_id, archived_at=None).count(),
        "sessions": PokerSession.query.filter_by(league_id=league_id).count(),
        "open_sessions": PokerSession.query.filter_by(league_id=league_id, status="open").count(),
        "events": LedgerEvent.query.filter_by(league_id=league_id, voided_at=None).count(),
    }


def create_player(league_id: str, display_name: str, slug: str) -> Player:
    player = make_player(league_id=league_id, display_name=display_name, slug=slug)
    db.session.add(player)
    return player


def unique_player_slug(league_id: str, display_name: str, requested_slug: str | None = None) -> str:
    base_slug = slugify(requested_slug or display_name, fallback="player")
    candidate = base_slug
    suffix = 2

    while Player.query.filter_by(league_id=league_id, slug=candidate).first() is not None:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1

    return candidate


def list_players_for_league(league_id: str) -> list[Player]:
    return (
        Player.query.filter_by(league_id=league_id)
        .order_by(Player.status.asc(), Player.display_name.asc())
        .all()
    )


def find_player_for_league(league_id: str, player_id: str) -> Player | None:
    return Player.query.filter_by(league_id=league_id, id=player_id).one_or_none()


def set_player_status(player: Player, status: str) -> Player:
    if status not in {"active", "archived"}:
        raise ValueError(f"Unsupported player status: {status}")

    player.status = status
    return player


def create_season(
    league_id: str,
    name: str,
    start_date: date | None = None,
    end_date: date | None = None,
    sort_order: int = 0,
) -> Season:
    season = Season(
        league_id=league_id,
        name=name.strip(),
        start_date=start_date,
        end_date=end_date,
        sort_order=sort_order,
    )
    db.session.add(season)
    return season


def next_sequence_on_date(league_id: str, session_date: date) -> int:
    current = (
        db.session.query(db.func.max(PokerSession.sequence_on_date))
        .filter_by(league_id=league_id, session_date=session_date)
        .scalar()
    )
    return int(current or 0) + 1


def create_poker_session(
    league_id: str,
    session_date: date,
    season_id: str | None = None,
    status: str = "closed",
) -> PokerSession:
    session = make_session(
        league_id=league_id,
        season_id=season_id,
        session_date=session_date,
        sequence_on_date=next_sequence_on_date(league_id, session_date),
        status=status,
    )
    db.session.add(session)
    return session


def list_sessions_for_league(league_id: str) -> list[PokerSession]:
    return (
        PokerSession.query.filter_by(league_id=league_id)
        .order_by(
            PokerSession.session_date.desc(),
            PokerSession.sequence_on_date.desc(),
            PokerSession.created_at.desc(),
        )
        .all()
    )


def find_session_for_league(league_id: str, session_id: str) -> PokerSession | None:
    return PokerSession.query.filter_by(league_id=league_id, id=session_id).one_or_none()


def set_session_status(session: PokerSession, status: str) -> PokerSession:
    if status not in {"open", "closed"}:
        raise ValueError(f"Unsupported session status: {status}")

    from boker.db_models import utc_now

    session.status = status
    if status == "open":
        session.opened_at = utc_now()
        session.closed_at = None
    else:
        session.closed_at = utc_now()
    return session


def player_name_exists(league_id: str, display_name: str) -> bool:
    return (
        Player.query.filter_by(
            league_id=league_id,
            normalized_name=normalize_lookup(display_name),
        ).first()
        is not None
    )


def player_name_taken(league_id: str, display_name: str, exclude_player_id: str) -> bool:
    return (
        Player.query.filter(
            Player.league_id == league_id,
            Player.normalized_name == normalize_lookup(display_name),
            Player.id != exclude_player_id,
        ).first()
        is not None
    )


def update_player(player: Player, display_name: str, notes: str | None) -> Player:
    player.display_name = display_name.strip()
    player.normalized_name = normalize_lookup(display_name)
    player.notes = notes.strip() if notes else None
    return player


def user_has_league_role(
    user_id: str,
    league_id: str,
    allowed_roles: set[str] | tuple[str, ...] | list[str],
) -> bool:
    membership = LeagueMembership.query.filter_by(
        user_id=user_id,
        league_id=league_id,
        disabled_at=None,
    ).one_or_none()
    return bool(membership and membership.role in set(allowed_roles))


def find_membership(league_id: str, user_id: str) -> LeagueMembership | None:
    return LeagueMembership.query.filter_by(
        league_id=league_id,
        user_id=user_id,
        disabled_at=None,
    ).one_or_none()


def list_members_for_league(league_id: str) -> list[tuple[LeagueMembership, User]]:
    return (
        db.session.query(LeagueMembership, User)
        .join(User, User.id == LeagueMembership.user_id)
        .filter(
            LeagueMembership.league_id == league_id,
            LeagueMembership.disabled_at.is_(None),
        )
        .order_by(LeagueMembership.created_at.asc())
        .all()
    )


def add_league_member(
    league_id: str,
    user_id: str,
    role: str,
    invited_by_user_id: str,
) -> LeagueMembership:
    existing = LeagueMembership.query.filter_by(
        league_id=league_id,
        user_id=user_id,
    ).one_or_none()
    if existing is not None:
        existing.role = role
        existing.invited_by_user_id = invited_by_user_id or None
        existing.disabled_at = None
        return existing

    membership = LeagueMembership(
        league_id=league_id,
        user_id=user_id,
        role=role,
        invited_by_user_id=invited_by_user_id or None,
    )
    db.session.add(membership)
    return membership


def remove_league_member(league_id: str, user_id: str) -> None:
    from boker.db_models import utc_now

    membership = LeagueMembership.query.filter_by(
        league_id=league_id,
        user_id=user_id,
        disabled_at=None,
    ).one_or_none()
    if membership and membership.role != "owner":
        membership.disabled_at = utc_now()


def set_league_member_role(league_id: str, user_id: str, role: str) -> LeagueMembership | None:
    if role not in {"manager", "viewer"}:
        raise ValueError(f"Unsupported member role: {role}")

    membership = LeagueMembership.query.filter_by(
        league_id=league_id,
        user_id=user_id,
        disabled_at=None,
    ).one_or_none()
    if membership is None or membership.role == "owner":
        return None

    membership.role = role
    return membership


def transfer_league_ownership(
    league: League,
    current_owner_user_id: str,
    new_owner_user_id: str,
) -> tuple[LeagueMembership, LeagueMembership] | None:
    if current_owner_user_id == new_owner_user_id:
        return None

    current_owner = LeagueMembership.query.filter_by(
        league_id=league.id,
        user_id=current_owner_user_id,
        disabled_at=None,
    ).one_or_none()
    new_owner = LeagueMembership.query.filter_by(
        league_id=league.id,
        user_id=new_owner_user_id,
        disabled_at=None,
    ).one_or_none()
    if current_owner is None or current_owner.role != "owner" or new_owner is None:
        return None

    current_owner.role = "manager"
    new_owner.role = "owner"
    league.created_by_user_id = new_owner_user_id
    return current_owner, new_owner


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------

def list_seasons_for_league(league_id: str, include_archived: bool = False) -> list[Season]:
    q = Season.query.filter_by(league_id=league_id)
    if not include_archived:
        q = q.filter(Season.archived_at.is_(None))
    return q.order_by(Season.sort_order.asc(), Season.created_at.asc()).all()


def find_season(league_id: str, season_id: str) -> Season | None:
    return Season.query.filter_by(league_id=league_id, id=season_id).one_or_none()


def update_season(
    season: Season,
    name: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Season:
    season.name = name.strip()
    season.start_date = start_date
    season.end_date = end_date
    return season


def archive_season(season: Season) -> Season:
    from datetime import datetime, timezone
    season.archived_at = datetime.now(timezone.utc)
    return season


def unarchive_season(season: Season) -> Season:
    season.archived_at = None
    return season


def delete_season(season: Season) -> None:
    PokerSession.query.filter_by(season_id=season.id).update({"season_id": None})
    db.session.delete(season)


def delete_league(league: League) -> None:
    from boker.db_models import LedgerEvent, LeagueMembership, Player, PokerSession, Season
    LedgerEvent.query.filter_by(league_id=league.id).delete(synchronize_session=False)
    PokerSession.query.filter_by(league_id=league.id).delete(synchronize_session=False)
    Player.query.filter_by(league_id=league.id).delete(synchronize_session=False)
    Season.query.filter_by(league_id=league.id).delete(synchronize_session=False)
    LeagueMembership.query.filter_by(league_id=league.id).delete(synchronize_session=False)
    db.session.delete(league)


def auto_assign_sessions_to_seasons(league_id: str) -> int:
    """Assign unassigned sessions to seasons based on date ranges.

    Only seasons with both start_date and end_date set are considered.
    Sessions with exactly one matching season are assigned; sessions that
    match zero or multiple seasons are left untouched (caller decides).
    Returns the number of sessions assigned.
    """
    eligible_seasons = [
        s for s in list_seasons_for_league(league_id, include_archived=False)
        if s.start_date is not None and s.end_date is not None
    ]
    if not eligible_seasons:
        return 0

    unassigned = PokerSession.query.filter_by(
        league_id=league_id, season_id=None
    ).all()
    assigned = 0
    for session in unassigned:
        matches = [
            s for s in eligible_seasons
            if s.start_date <= session.session_date <= s.end_date
        ]
        if len(matches) == 1:
            session.season_id = matches[0].id
            assigned += 1
    return assigned
