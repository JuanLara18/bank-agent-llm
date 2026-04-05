"""Repository layer — all database access goes through these classes.

Never use raw SQLAlchemy queries outside this module.
Each repository is instantiated with a Session and its lifetime matches
the session's lifetime (request, pipeline run, etc.).
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from bank_agent_llm.storage.models import (
    Account,
    Category,
    FileProcessingRun,
    MerchantCache,
    PipelineRun,
    ProcessedEmail,
    Transaction,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ─── Account ──────────────────────────────────────────────────────────────────

class AccountRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_or_create(
        self,
        bank_name: str,
        account_number: str,
        currency: str = "COP",
        owner_email: str | None = None,
    ) -> Account:
        """Return existing account or create a new one (matched by account_number hash)."""
        account_hash = _sha256(account_number)
        stmt = select(Account).where(Account.account_number_hash == account_hash)
        account = self._s.execute(stmt).scalar_one_or_none()
        if account is None:
            account = Account(
                bank_name=bank_name,
                account_number_hash=account_hash,
                currency=currency,
                owner_email=owner_email,
            )
            self._s.add(account)
            self._s.flush()
        return account

    def all(self) -> list[Account]:
        return list(self._s.execute(select(Account)).scalars())


# ─── Category ────────────────────────────────────────────────────────────────

class CategoryRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_or_create(self, name: str, parent_id: int | None = None) -> Category:
        stmt = select(Category).where(Category.name == name)
        category = self._s.execute(stmt).scalar_one_or_none()
        if category is None:
            category = Category(name=name, parent_id=parent_id)
            self._s.add(category)
            self._s.flush()
        return category

    def all(self) -> list[Category]:
        return list(self._s.execute(select(Category)).scalars())


# ─── Transaction ─────────────────────────────────────────────────────────────

class TransactionRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add_or_skip(self, transaction: Transaction) -> tuple[Transaction, bool]:
        """Insert a transaction, skipping if the dedup constraint would fire.

        Returns:
            (transaction, created) — created is False if it was a duplicate.
        """
        stmt = select(Transaction).where(
            Transaction.account_id == transaction.account_id,
            Transaction.date == transaction.date,
            Transaction.amount == transaction.amount,
            Transaction.description_hash == transaction.description_hash,
            Transaction.position_in_statement == transaction.position_in_statement,
        )
        existing = self._s.execute(stmt).scalar_one_or_none()
        if existing:
            return existing, False
        self._s.add(transaction)
        self._s.flush()
        return transaction, True

    def find_by_account(self, account_id: int) -> list[Transaction]:
        stmt = select(Transaction).where(Transaction.account_id == account_id)
        return list(self._s.execute(stmt).scalars())

    def find_uncategorized(self) -> list[Transaction]:
        stmt = select(Transaction).where(Transaction.category_id.is_(None))
        return list(self._s.execute(stmt).scalars())

    def count(self) -> int:
        return self._s.query(Transaction).count()

    def delete_before(self, cutoff: date) -> int:
        """Delete transactions with date < cutoff. Returns number deleted."""
        stmt = select(Transaction).where(Transaction.date < cutoff)
        rows = list(self._s.execute(stmt).scalars())
        for row in rows:
            self._s.delete(row)
        self._s.flush()
        return len(rows)


# ─── ProcessedEmail ──────────────────────────────────────────────────────────

class ProcessedEmailRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def is_processed(self, message_id: str) -> bool:
        stmt = select(ProcessedEmail).where(ProcessedEmail.message_id == message_id)
        return self._s.execute(stmt).scalar_one_or_none() is not None

    def mark_processed(
        self, email_account: str, message_id: str, subject: str | None = None
    ) -> ProcessedEmail:
        record = ProcessedEmail(
            email_account=email_account, message_id=message_id, subject=subject
        )
        self._s.add(record)
        self._s.flush()
        return record


# ─── FileProcessingRun ───────────────────────────────────────────────────────

class FileProcessingRunRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def is_processed(self, file_hash: str) -> bool:
        """Return True if the file should be skipped on the next import run.

        - "success" → already imported, skip.
        - "skipped" → no parser exists; re-importing same bytes yields same outcome, skip.
        - "error"   → parse failed; may succeed after a fix, so retry (return False).
        """
        stmt = select(FileProcessingRun).where(
            FileProcessingRun.file_hash == file_hash,
            FileProcessingRun.status.in_(["success", "skipped"]),
        )
        return self._s.execute(stmt).scalar_one_or_none() is not None

    def create(
        self,
        file_path: str,
        file_hash: str,
        status: str,
        bank_name: str | None = None,
        transaction_count: int = 0,
        error_message: str | None = None,
    ) -> FileProcessingRun:
        run = FileProcessingRun(
            file_path=file_path,
            file_hash=file_hash,
            status=status,
            bank_name=bank_name,
            transaction_count=transaction_count,
            error_message=error_message,
        )
        self._s.add(run)
        self._s.flush()
        return run


# ─── PipelineRun ─────────────────────────────────────────────────────────────

class PipelineRunRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def start(self) -> PipelineRun:
        run = PipelineRun(status="running")
        self._s.add(run)
        self._s.flush()
        return run

    def finish(
        self,
        run: PipelineRun,
        status: str,
        stages_completed: list[str] | None = None,
        fetched: int = 0,
        parsed: int = 0,
        enriched: int = 0,
    ) -> None:
        from datetime import datetime

        run.status = status
        run.stages_completed = ",".join(stages_completed or [])
        run.transactions_fetched = fetched
        run.transactions_parsed = parsed
        run.transactions_enriched = enriched
        run.finished_at = datetime.utcnow()
        self._s.flush()

    def latest(self) -> PipelineRun | None:
        stmt = select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(1)
        return self._s.execute(stmt).scalar_one_or_none()


# ─── Enrichment ───────────────────────────────────────────────────────────────

class EnrichmentRepository:
    """Data access for the enrichment layer (tags + merchant cache)."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def pending_transactions(
        self, *, include_tagged: bool = False
    ) -> list[Transaction]:
        """Return transactions that need enrichment.

        By default only tag_source='pending'. With include_tagged=True also
        returns previously tagged transactions (for re-runs), never manual ones.
        """
        if include_tagged:
            stmt = select(Transaction).where(Transaction.tag_source != "manual")
        else:
            stmt = select(Transaction).where(Transaction.tag_source == "pending")
        return list(self._s.execute(stmt).scalars().all())

    def save_tags(
        self,
        transaction_id: int,
        tags: list[str],
        merchant_name: str | None,
        source: str,
    ) -> None:
        tx = self._s.get(Transaction, transaction_id)
        if tx is None:
            return
        tx.tags = tags
        tx.tag_source = source
        if merchant_name:
            tx.merchant_name = merchant_name
        self._s.flush()

    def get_merchant_cache(self, merchant_key: str) -> MerchantCache | None:
        stmt = select(MerchantCache).where(MerchantCache.merchant_key == merchant_key)
        cached = self._s.execute(stmt).scalar_one_or_none()
        if cached:
            cached.hit_count += 1
            self._s.flush()
        return cached

    def upsert_merchant_cache(
        self,
        merchant_key: str,
        tags: list[str],
        merchant_name: str,
        source: str,
    ) -> None:
        existing = self._s.execute(
            select(MerchantCache).where(MerchantCache.merchant_key == merchant_key)
        ).scalar_one_or_none()

        if existing:
            existing.tags = tags
            existing.merchant_name = merchant_name
            existing.source = source
            existing.hit_count += 1
        else:
            self._s.add(MerchantCache(
                merchant_key=merchant_key,
                tags=tags,
                merchant_name=merchant_name,
                source=source,
            ))
        self._s.flush()
