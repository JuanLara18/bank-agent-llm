"""Remove cross-file duplicate transactions.

Credit-card statements carry forward all prior-month transactions.  When
multiple monthly statements for the same card are imported, identical
transactions (same account, date, amount, description) appear once per file.
The original dedup constraint included ``position_in_statement`` which differs
across files, so these duplicates were not caught.

This data-only migration keeps the earliest-inserted row (lowest ``id``) for
each (account_id, date, amount, description_hash) group and deletes the rest.

Revision ID: 004
Revises: 003
Create Date: 2026-04-12
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    conn = op.get_bind()

    # Identify the IDs to DELETE: for each logical group keep only MIN(id).
    dupes = conn.execute(sa.text("""
        SELECT id FROM transactions
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM transactions
            GROUP BY account_id, date, amount, description_hash
        )
        AND EXISTS (
            SELECT 1 FROM transactions t2
            WHERE t2.account_id = transactions.account_id
              AND t2.date       = transactions.date
              AND t2.amount     = transactions.amount
              AND t2.description_hash = transactions.description_hash
              AND t2.id < transactions.id
        )
    """)).fetchall()

    ids_to_delete = [row[0] for row in dupes]

    if not ids_to_delete:
        log.info("No cross-file duplicates found — nothing to clean up.")
        return

    log.info(
        "Deleting %d cross-file duplicate transaction(s).", len(ids_to_delete),
    )

    # Delete in batches to keep transaction size reasonable.
    batch_size = 500
    for i in range(0, len(ids_to_delete), batch_size):
        batch = ids_to_delete[i : i + batch_size]
        placeholders = ", ".join(str(tid) for tid in batch)
        conn.execute(sa.text(f"DELETE FROM transactions WHERE id IN ({placeholders})"))


def downgrade() -> None:
    # Data-only migration — deleted rows can be recovered by re-importing
    # the original PDF files.
    pass
