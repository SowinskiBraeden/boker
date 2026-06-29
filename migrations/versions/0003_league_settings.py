"""add per-league eligible_min_sessions and break_even_cents

Revision ID: 0003_league_settings
Revises: 0002_league_public_key
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_league_settings"
down_revision = "0003_site_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leagues") as batch_op:
        batch_op.add_column(sa.Column(
            "eligible_min_sessions", sa.Integer(), nullable=False, server_default="3"
        ))
        batch_op.add_column(sa.Column(
            "break_even_cents", sa.Integer(), nullable=False, server_default="100"
        ))


def downgrade() -> None:
    with op.batch_alter_table("leagues") as batch_op:
        batch_op.drop_column("break_even_cents")
        batch_op.drop_column("eligible_min_sessions")
