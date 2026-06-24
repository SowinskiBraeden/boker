"""public multi-league foundation

Revision ID: 0001_public_foundation
Revises: 
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_public_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)

    op.create_table(
        "leagues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("visibility IN ('private', 'public')", name="ck_leagues_visibility"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_leagues_created_by_user_id"), "leagues", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_leagues_slug"), "leagues", ["slug"], unique=False)

    op.create_table(
        "league_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("league_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("invited_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('owner', 'manager', 'viewer')", name="ck_memberships_role"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("league_id", "user_id", name="uq_memberships_league_user"),
    )
    op.create_index(op.f("ix_league_memberships_league_id"), "league_memberships", ["league_id"], unique=False)
    op.create_index(op.f("ix_league_memberships_user_id"), "league_memberships", ["user_id"], unique=False)

    op.create_table(
        "players",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("league_id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("normalized_name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("linked_user_id", sa.String(length=36), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_players_status"),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("league_id", "id", name="uq_players_league_id"),
        sa.UniqueConstraint("league_id", "normalized_name", name="uq_players_name"),
        sa.UniqueConstraint("league_id", "slug", name="uq_players_slug"),
    )
    op.create_index(op.f("ix_players_league_id"), "players", ["league_id"], unique=False)

    op.create_table(
        "seasons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("league_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("start_date IS NULL OR end_date IS NULL OR start_date <= end_date", name="ck_seasons_date_order"),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("league_id", "id", name="uq_seasons_league_id"),
        sa.UniqueConstraint("league_id", "name", name="uq_seasons_name"),
    )
    op.create_index(op.f("ix_seasons_league_id"), "seasons", ["league_id"], unique=False)

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("league_id", sa.String(length=36), nullable=False),
        sa.Column("season_id", sa.String(length=36), nullable=True),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("sequence_on_date", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence_on_date > 0", name="ck_sessions_sequence_positive"),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_sessions_status"),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["league_id", "season_id"], ["seasons.league_id", "seasons.id"], name="fk_sessions_season_same_league", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("league_id", "id", name="uq_sessions_league_id"),
        sa.UniqueConstraint("league_id", "session_date", "sequence_on_date", name="uq_sessions_date_sequence"),
    )
    op.create_index(op.f("ix_sessions_league_id"), "sessions", ["league_id"], unique=False)
    op.create_index(op.f("ix_sessions_session_date"), "sessions", ["session_date"], unique=False)

    op.create_table(
        "ledger_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("league_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("player_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("legacy_event_id", sa.String(length=80), nullable=True),
        sa.Column("legacy_player_name", sa.String(length=160), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("event_type IN ('buyin', 'cashout', 'debt_repayment', 'front', 'front_collected', 'front_writeoff', 'note', 'paid', 'paid_out', 'payout_carry_in', 'rollover_in', 'rollover_out', 'session_close', 'session_open', 'writeoff')", name="ck_events_type"),
        sa.CheckConstraint("player_id IS NOT NULL OR event_type IN ('note', 'session_open', 'session_close')", name="ck_events_player_required"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["league_id", "player_id"], ["players.league_id", "players.id"], name="fk_events_player_same_league", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["league_id", "session_id"], ["sessions.league_id", "sessions.id"], name="fk_events_session_same_league", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voided_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ledger_events_league_id"), "ledger_events", ["league_id"], unique=False)
    op.create_index(op.f("ix_ledger_events_player_id"), "ledger_events", ["player_id"], unique=False)
    op.create_index(op.f("ix_ledger_events_session_id"), "ledger_events", ["session_id"], unique=False)
    op.create_index("ix_events_league_created", "ledger_events", ["league_id", "created_at"], unique=False)
    op.create_index("ix_events_league_session_created", "ledger_events", ["league_id", "session_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_events_league_session_created", table_name="ledger_events")
    op.drop_index("ix_events_league_created", table_name="ledger_events")
    op.drop_index(op.f("ix_ledger_events_session_id"), table_name="ledger_events")
    op.drop_index(op.f("ix_ledger_events_player_id"), table_name="ledger_events")
    op.drop_index(op.f("ix_ledger_events_league_id"), table_name="ledger_events")
    op.drop_table("ledger_events")
    op.drop_index(op.f("ix_sessions_session_date"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_league_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_seasons_league_id"), table_name="seasons")
    op.drop_table("seasons")
    op.drop_index(op.f("ix_players_league_id"), table_name="players")
    op.drop_table("players")
    op.drop_index(op.f("ix_league_memberships_user_id"), table_name="league_memberships")
    op.drop_index(op.f("ix_league_memberships_league_id"), table_name="league_memberships")
    op.drop_table("league_memberships")
    op.drop_index(op.f("ix_leagues_slug"), table_name="leagues")
    op.drop_index(op.f("ix_leagues_public_key"), table_name="leagues")
    op.drop_index(op.f("ix_leagues_created_by_user_id"), table_name="leagues")
    op.drop_table("leagues")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
