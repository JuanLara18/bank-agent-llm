"""Remove accounts that have zero transactions.

Empty accounts are created when a PDF file is opened and the parser extracts
an account number but fails to parse any transactions from the file.

Revision ID: 005
Revises: 004
Create Date: 2026-04-12
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "DELETE FROM accounts "
        "WHERE id NOT IN (SELECT DISTINCT account_id FROM transactions)"
    ))
    log.info("Removed %d empty account(s).", result.rowcount)


def downgrade() -> None:
    # Accounts had no data — nothing meaningful to restore.
    pass
