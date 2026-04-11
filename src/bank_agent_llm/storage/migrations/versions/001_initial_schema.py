"""Initial schema — all 6 tables.

Revision ID: 001
Revises: —
Create Date: 2026-04-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("bank_name", sa.String(100), nullable=False),
        sa.Column("account_number_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("owner_email", sa.String(255), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="COP"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

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

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("transaction_time", sa.Time, nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="COP"),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("raw_description", sa.Text, nullable=False),
        sa.Column("normalized_description", sa.Text, nullable=True),
        sa.Column(
            "category_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category_confidence", sa.Float, nullable=True),
        sa.Column("source_file", sa.Text, nullable=False),
        sa.Column("description_hash", sa.String(64), nullable=False),
        sa.Column("position_in_statement", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "account_id",
            "date",
            "amount",
            "description_hash",
            "position_in_statement",
            name="uq_transaction_dedup",
        ),
    )

    op.create_table(
        "processed_emails",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email_account", sa.String(255), nullable=False),
        sa.Column("message_id", sa.Text, unique=True, nullable=False),
        sa.Column("subject", sa.Text, nullable=True),
        sa.Column("processed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "file_processing_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("transaction_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("processed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stages_completed", sa.Text, nullable=True),
        sa.Column("transactions_fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("transactions_parsed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("transactions_enriched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pipeline_runs")
    op.drop_table("file_processing_runs")
    op.drop_table("processed_emails")
    op.drop_table("transactions")
    op.drop_table("categories")
    op.drop_table("accounts")
