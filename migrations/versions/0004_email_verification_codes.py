"""add email verification code fields

Revision ID: 0004_email_verification_codes
Revises: 0003_league_settings
Create Date: 2026-06-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_email_verification_codes"
down_revision = "0003_league_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("email_verification_code_hash", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("email_verification_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("email_verification_sent_at")
        batch_op.drop_column("email_verification_code_hash")
