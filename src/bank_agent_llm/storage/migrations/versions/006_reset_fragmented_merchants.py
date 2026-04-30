"""Reset LLM-tagged transactions that now match keyword rules.

New keyword rules were added for merchants that the LLM tagged with
inconsistent names (e.g. "Suc Virt TC Visa" vs "SUC VIRT TC VISA").
This migration clears their enrichment fields so that `bank-agent enrich`
re-processes them with the deterministic rules.

Revision ID: 006
Revises: 005
Create Date: 2026-04-12
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

# Patterns that now have keyword rules — match any description containing these.
_PATTERNS = [
    "PAGO SUC VIRT TC",
    "TRANSFERENCIA A NEQUI",
    "TRANSFERENCIAS A NEQUI",
    "TRANSFERENCIA CTA SUC VIRTUAL",
    "CUOTA MANEJO TRJ",
    "AJUSTE INTERES",
    "MERCADOPAGO",
    "PAGO PSE PAGOS ELECTRONICOS",
    "PAGO PSE AVAL",
    "COLOMBIA TELECOMUNI",
    "ENEL COLOMBIA",
    "CARDIF S.A.",
    "CINEMARK",
]


def upgrade() -> None:
    conn = op.get_bind()
    total = 0
    for pattern in _PATTERNS:
        result = conn.execute(sa.text(
            "UPDATE transactions "
            "SET tag_source = 'pending', tags = '[]', merchant_name = NULL "
            "WHERE tag_source IN ('llm', 'llm_cache') "
            "  AND UPPER(raw_description) LIKE :pat"
        ), {"pat": f"%{pattern.upper()}%"})
        if result.rowcount:
            log.info("  Reset %d rows matching '%s'", result.rowcount, pattern)
            total += result.rowcount
    log.info("Reset %d transaction(s) for merchant re-enrichment.", total)


def downgrade() -> None:
    # Cannot restore previous LLM assignments — re-run `bank-agent enrich`.
    pass
