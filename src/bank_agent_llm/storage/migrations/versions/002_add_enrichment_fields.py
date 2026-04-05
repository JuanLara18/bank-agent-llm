"""Add enrichment fields to transactions and merchant_cache table.

Revision ID: 002
Revises: 001
Create Date: 2026-04-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enrichment columns on transactions
    op.add_column("transactions", sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("transactions", sa.Column("tag_source", sa.String(20), nullable=False, server_default="pending"))
    op.add_column("transactions", sa.Column("merchant_name", sa.String(120), nullable=True))

    # Merchant cache — reuse Ollama results across identical descriptions
    op.create_table(
        "merchant_cache",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("merchant_key", sa.String(200), unique=True, nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("merchant_name", sa.String(120), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_merchant_cache_key", "merchant_cache", ["merchant_key"])


def downgrade() -> None:
    op.drop_index("ix_merchant_cache_key", "merchant_cache")
    op.drop_table("merchant_cache")
    op.drop_column("transactions", "merchant_name")
    op.drop_column("transactions", "tag_source")
    op.drop_column("transactions", "tags")
