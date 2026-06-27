#!/usr/bin/env python3
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from db import db

if db is None:  # pragma: no cover - imported only when DB dependencies exist.
    raise RuntimeError("Database dependencies are not installed.")


LEAGUE_ROLES = ("owner", "manager", "viewer")
PLAYER_STATUSES = ("active", "archived")
LEAGUE_VISIBILITIES = ("private", "public")
SESSION_STATUSES = ("open", "closed")

CANONICAL_EVENT_TYPES = {
    "buyin",
    "front",
    "rollover_in",
    "payout_carry_in",
    "cashout",
    "paid_out",
    "rollover_out",
    "debt_repayment",
    "writeoff",
    "note",
    "session_open",
    "session_close",
}

EVENT_TYPE_ALIASES = {
    "paid": "paid_out",
    "front_collected": "debt_repayment",
    "front_writeoff": "writeoff",
}

SUPPORTED_EVENT_TYPES = CANONICAL_EVENT_TYPES | set(EVENT_TYPE_ALIASES)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


def normalize_lookup(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def canonical_event_type(event_type: str) -> str:
    normalized = event_type.strip().lower()
    return EVENT_TYPE_ALIASES.get(normalized, normalized)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email_verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    disabled_at = db.Column(db.DateTime(timezone=True), nullable=True)


class League(TimestampMixin, db.Model):
    __tablename__ = "leagues"

    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(120), nullable=False, index=True)
    public_key = db.Column(db.String(12), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    visibility = db.Column(db.String(20), nullable=False, default="private")
    created_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)
    eligible_min_sessions = db.Column(db.Integer, nullable=False, default=3)
    break_even_cents = db.Column(db.Integer, nullable=False, default=100)

    __table_args__ = (
        db.CheckConstraint(
            f"visibility IN {LEAGUE_VISIBILITIES}",
            name="ck_leagues_visibility",
        ),
    )

    @property
    def url_ref(self) -> str:
        return f"{self.slug}-{self.public_key}"


class LeagueMembership(db.Model):
    __tablename__ = "league_memberships"

    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    league_id = db.Column(
        db.String(36),
        db.ForeignKey("leagues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(20), nullable=False)
    invited_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    disabled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("league_id", "user_id", name="uq_memberships_league_user"),
        db.CheckConstraint(f"role IN {LEAGUE_ROLES}", name="ck_memberships_role"),
    )


class Player(TimestampMixin, db.Model):
    __tablename__ = "players"

    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    league_id = db.Column(
        db.String(36),
        db.ForeignKey("leagues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name = db.Column(db.String(160), nullable=False)
    normalized_name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active")
    linked_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("league_id", "normalized_name", name="uq_players_name"),
        db.UniqueConstraint("league_id", "slug", name="uq_players_slug"),
        db.UniqueConstraint("league_id", "id", name="uq_players_league_id"),
        db.CheckConstraint(f"status IN {PLAYER_STATUSES}", name="ck_players_status"),
    )


class Season(TimestampMixin, db.Model):
    __tablename__ = "seasons"

    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    league_id = db.Column(
        db.String(36),
        db.ForeignKey("leagues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(160), nullable=False)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("league_id", "name", name="uq_seasons_name"),
        db.UniqueConstraint("league_id", "id", name="uq_seasons_league_id"),
        db.CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR start_date <= end_date",
            name="ck_seasons_date_order",
        ),
    )


class PokerSession(TimestampMixin, db.Model):
    __tablename__ = "sessions"

    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    league_id = db.Column(
        db.String(36),
        db.ForeignKey("leagues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    season_id = db.Column(db.String(36), nullable=True)
    session_date = db.Column(db.Date, nullable=False, index=True)
    sequence_on_date = db.Column(db.Integer, nullable=False, default=1)
    label = db.Column(db.String(80), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="closed")
    opened_at = db.Column(db.DateTime(timezone=True), nullable=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            "league_id",
            "session_date",
            "sequence_on_date",
            name="uq_sessions_date_sequence",
        ),
        db.UniqueConstraint("league_id", "id", name="uq_sessions_league_id"),
        db.ForeignKeyConstraint(
            ["league_id", "season_id"],
            ["seasons.league_id", "seasons.id"],
            name="fk_sessions_season_same_league",
            ondelete="RESTRICT",
        ),
        db.CheckConstraint("sequence_on_date > 0", name="ck_sessions_sequence_positive"),
        db.CheckConstraint(f"status IN {SESSION_STATUSES}", name="ck_sessions_status"),
    )

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        return f"{self.session_date.isoformat()} - S{self.sequence_on_date}"


class LedgerEvent(db.Model):
    __tablename__ = "ledger_events"

    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    league_id = db.Column(db.String(36), nullable=False, index=True)
    session_id = db.Column(db.String(36), nullable=False, index=True)
    player_id = db.Column(db.String(36), nullable=True, index=True)
    event_type = db.Column(db.String(40), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False, default=0)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    created_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    legacy_event_id = db.Column(db.String(80), nullable=True)
    legacy_player_name = db.Column(db.String(160), nullable=True)
    voided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    voided_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    void_reason = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["league_id", "session_id"],
            ["sessions.league_id", "sessions.id"],
            name="fk_events_session_same_league",
            ondelete="CASCADE",
        ),
        db.ForeignKeyConstraint(
            ["league_id", "player_id"],
            ["players.league_id", "players.id"],
            name="fk_events_player_same_league",
            ondelete="RESTRICT",
        ),
        db.CheckConstraint(
            f"event_type IN {tuple(sorted(SUPPORTED_EVENT_TYPES))}",
            name="ck_events_type",
        ),
        db.CheckConstraint(
            "player_id IS NOT NULL OR event_type IN ('note', 'session_open', 'session_close')",
            name="ck_events_player_required",
        ),
        db.Index("ix_events_league_created", "league_id", "created_at"),
        db.Index("ix_events_league_session_created", "league_id", "session_id", "created_at"),
    )


def make_user(email: str, password_hash: str) -> User:
    return User(email=email.strip().casefold(), password_hash=password_hash)


def make_player(league_id: str, display_name: str, slug: str) -> Player:
    return Player(
        league_id=league_id,
        display_name=display_name.strip(),
        normalized_name=normalize_lookup(display_name),
        slug=slug.strip().lower(),
    )


def make_session(
    league_id: str,
    session_date: date,
    sequence_on_date: int,
    season_id: str | None = None,
    status: str = "closed",
) -> PokerSession:
    return PokerSession(
        league_id=league_id,
        season_id=season_id,
        session_date=session_date,
        sequence_on_date=sequence_on_date,
        status=status,
    )
