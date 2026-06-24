"""add league public key

Revision ID: 0002_league_public_key
Revises: 0001_public_foundation
Create Date: 2026-06-23
"""
from __future__ import annotations

import secrets
import string

from alembic import op
import sqlalchemy as sa


revision = "0002_league_public_key"
down_revision = "0001_public_foundation"
branch_labels = None
depends_on = None

ALPHABET = string.ascii_lowercase + string.digits


def _key(existing: set[str], length: int = 6) -> str:
    while True:
        value = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if value not in existing:
            existing.add(value)
            return value


def upgrade() -> None:
    op.add_column("leagues", sa.Column("public_key", sa.String(length=12), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM leagues")).mappings().all()
    existing: set[str] = set()
    for row in rows:
        bind.execute(
            sa.text("UPDATE leagues SET public_key = :public_key WHERE id = :id"),
            {"public_key": _key(existing), "id": row["id"]},
        )

    with op.batch_alter_table("leagues") as batch_op:
        batch_op.alter_column("public_key", existing_type=sa.String(length=12), nullable=False)
        batch_op.create_index("ix_leagues_public_key", ["public_key"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("leagues") as batch_op:
        batch_op.drop_index("ix_leagues_public_key")
        batch_op.drop_column("public_key")
