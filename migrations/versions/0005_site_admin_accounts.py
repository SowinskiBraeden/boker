"""add account-backed site admin flag

Revision ID: 0005_site_admin_accounts
Revises: 0004_email_verification_codes
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_site_admin_accounts"
down_revision = "0004_email_verification_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "is_site_admin" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "is_site_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "is_site_admin" in columns:
        op.drop_column("users", "is_site_admin")
