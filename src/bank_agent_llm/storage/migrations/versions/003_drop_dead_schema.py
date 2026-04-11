"""Drop dead schema: categories table + unused transaction columns.

The `categories` table and its foreign-key columns were scaffolded in M1 but
never used once the enrichment pipeline settled on a JSON ``tags`` column
populated by the rules engine and Ollama. The following fields are NULL in
100% of rows across all real data and are not written by any code path:

- ``transactions.transaction_time`` — parsers never populate this
- ``transactions.normalized_description`` — no normalization stage exists
- ``transactions.category_id`` / ``category_confidence`` — superseded by
  ``tags`` + ``tag_source``
- the ``categories`` table itself (0 rows in production)

Revision ID: 003
Revises: 002
Create Date: 2026-04-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite requires batch mode to drop columns with foreign keys.
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("category_confidence")
        batch.drop_column("category_id")
        batch.drop_column("normalized_description")
        batch.drop_column("transaction_time")

    op.drop_table("categories")


def downgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column(
            "parent_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("color", sa.String(7), nullable=True),
    )

    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("transaction_time", sa.Time, nullable=True))
        batch.add_column(sa.Column("normalized_description", sa.Text, nullable=True))
        batch.add_column(
            sa.Column(
                "category_id",
                sa.Integer,
                sa.ForeignKey("categories.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("category_confidence", sa.Float, nullable=True))
