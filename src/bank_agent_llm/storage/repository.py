"""Repository layer — all database access goes through these classes.

Never use raw SQLAlchemy queries outside this module.
Each repository is instantiated with a Session and its lifetime matches
the session's lifetime (request, pipeline run, etc.).
"""

from __future__ import annotations

import hashlib
from datetime import date

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
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
        """Return True only if the file was already imported successfully.

        Only "success" blocks re-processing. "skipped" (no parser matched) and
        "error" are retried on the next run so that fixing a parser or adding
        a new one automatically picks up previously-dropped files.
        """
        stmt = select(FileProcessingRun).where(
            FileProcessingRun.file_hash == file_hash,
            FileProcessingRun.status == "success",
        )
        return self._s.execute(stmt).scalar_one_or_none() is not None

    def record_outcome(
        self,
        file_path: str,
        file_hash: str,
        status: str,
        bank_name: str | None = None,
        transaction_count: int = 0,
        error_message: str | None = None,
    ) -> FileProcessingRun:
        """Upsert a processing outcome keyed by file_hash.

        Updates the existing row if one exists (so a previously-skipped file
        that now parses correctly overwrites its own record), else inserts.
        """
        existing = self._s.execute(
            select(FileProcessingRun).where(FileProcessingRun.file_hash == file_hash)
        ).scalar_one_or_none()
        if existing is not None:
            existing.file_path = file_path
            existing.status = status
            existing.bank_name = bank_name
            existing.transaction_count = transaction_count
            existing.error_message = error_message
            self._s.flush()
            return existing
        return self.create(
            file_path, file_hash, status,
            bank_name=bank_name,
            transaction_count=transaction_count,
            error_message=error_message,
        )

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


# ─── Stats ────────────────────────────────────────────────────────────────────

@dataclass
class AccountSummary:
    bank_name: str
    total: int
    date_min: date | None
    date_max: date | None
    total_debit: Decimal
    total_credit: Decimal


@dataclass
class MonthlySummary:
    year: int
    month: int
    debit: Decimal
    credit: Decimal

    @property
    def label(self) -> str:
        import calendar
        return f"{calendar.month_abbr[self.month]} {self.year}"


@dataclass
class TagSpending:
    tag: str
    total: Decimal
    count: int


@dataclass
class MerchantSpending:
    merchant: str
    total: Decimal
    count: int


@dataclass
class DayOfWeekSpending:
    """Aggregated spending per day of week (0=Monday … 6=Sunday)."""
    weekday: int          # 0–6
    label: str            # "Lunes", "Martes", …
    total: Decimal
    count: int


@dataclass
class StatusReport:
    total_transactions: int = 0
    pending_enrichment: int = 0
    date_min: date | None = None
    date_max: date | None = None
    total_debit: Decimal = field(default_factory=lambda: Decimal("0"))
    total_credit: Decimal = field(default_factory=lambda: Decimal("0"))
    accounts: list[AccountSummary] = field(default_factory=list)
    monthly: list[MonthlySummary] = field(default_factory=list)
    top_tags: list[TagSpending] = field(default_factory=list)
    top_merchants: list[MerchantSpending] = field(default_factory=list)
    by_weekday: list[DayOfWeekSpending] = field(default_factory=list)
    tag_source_counts: dict[str, int] = field(default_factory=dict)


_WEEKDAY_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


class StatsRepository:
    """Read-only analytics queries for the status dashboard."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def all_transactions(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        account_ids: list[int] | None = None,
        include_cancelled: bool = True,
    ) -> list[Transaction]:
        """Return transactions matching the given filters."""
        stmt = select(Transaction)
        if date_from:
            stmt = stmt.where(Transaction.date >= date_from)
        if date_to:
            stmt = stmt.where(Transaction.date <= date_to)
        if account_ids:
            stmt = stmt.where(Transaction.account_id.in_(account_ids))
        if not include_cancelled:
            stmt = stmt.where(~Transaction.tags.contains("cancelada"))
        return list(self._s.execute(stmt).scalars())

    def build_report(self, top_n: int = 10) -> StatusReport:
        report = StatusReport()

        txs = list(self._s.execute(select(Transaction)).scalars())
        if not txs:
            return report

        report.total_transactions = len(txs)
        report.pending_enrichment = sum(1 for t in txs if t.tag_source == "pending")

        debits = [t for t in txs if t.direction == "debit"]
        credits = [t for t in txs if t.direction == "credit"]

        all_dates = [t.date for t in txs if t.date]
        if all_dates:
            report.date_min = min(all_dates)
            report.date_max = max(all_dates)

        report.total_debit = sum((t.amount for t in debits), Decimal("0"))
        report.total_credit = sum((t.amount for t in credits), Decimal("0"))

        # ── Per-account summary ───────────────────────────────────────────────
        accounts = list(self._s.execute(select(Account)).scalars())
        for acc in accounts:
            acc_txs = [t for t in txs if t.account_id == acc.id]
            if not acc_txs:
                continue
            acc_dates = [t.date for t in acc_txs if t.date]
            report.accounts.append(AccountSummary(
                bank_name=acc.bank_name,
                total=len(acc_txs),
                date_min=min(acc_dates) if acc_dates else None,
                date_max=max(acc_dates) if acc_dates else None,
                total_debit=sum(
                    (t.amount for t in acc_txs if t.direction == "debit"), Decimal("0")
                ),
                total_credit=sum(
                    (t.amount for t in acc_txs if t.direction == "credit"), Decimal("0")
                ),
            ))

        # ── Monthly summary (expense debits only) ─────────────────────────────
        monthly: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(
            lambda: {"debit": Decimal("0"), "credit": Decimal("0")}
        )
        for t in txs:
            if t.date:
                key = (t.date.year, t.date.month)
                monthly[key][t.direction] += t.amount
        report.monthly = [
            MonthlySummary(year=y, month=m, debit=v["debit"], credit=v["credit"])
            for (y, m), v in sorted(monthly.items())
        ]

        # ── Top tags (expense debits, leaf tags only) ─────────────────────────
        from bank_agent_llm.enrichment.tags import get_taxonomy
        taxonomy = get_taxonomy()
        tag_totals: dict[str, tuple[Decimal, int]] = defaultdict(lambda: (Decimal("0"), 0))
        for t in txs:
            if t.direction == "debit" and t.tag_source != "pending":
                primary = taxonomy.primary_tag(t.tags)
                if primary and taxonomy.is_expense(primary):
                    total, cnt = tag_totals[primary]
                    tag_totals[primary] = (total + t.amount, cnt + 1)
        report.top_tags = sorted(
            [TagSpending(tag=tag, total=total, count=cnt)
             for tag, (total, cnt) in tag_totals.items()],
            key=lambda x: x.total,
            reverse=True,
        )[:top_n]

        # ── Top merchants ─────────────────────────────────────────────────────
        merchant_totals: dict[str, tuple[Decimal, int]] = defaultdict(lambda: (Decimal("0"), 0))
        for t in txs:
            if t.direction == "debit":
                name = t.merchant_name or t.raw_description[:30]
                total, cnt = merchant_totals[name]
                merchant_totals[name] = (total + t.amount, cnt + 1)
        report.top_merchants = sorted(
            [MerchantSpending(merchant=m, total=total, count=cnt)
             for m, (total, cnt) in merchant_totals.items()],
            key=lambda x: x.total,
            reverse=True,
        )[:top_n]

        # ── Spending by day of week (expense debits) ──────────────────────────
        weekday_totals: dict[int, tuple[Decimal, int]] = defaultdict(lambda: (Decimal("0"), 0))
        for t in txs:
            if t.direction == "debit" and t.date:
                wd = t.date.weekday()  # 0=Monday
                total, cnt = weekday_totals[wd]
                weekday_totals[wd] = (total + t.amount, cnt + 1)
        report.by_weekday = [
            DayOfWeekSpending(
                weekday=wd,
                label=_WEEKDAY_ES[wd],
                total=total,
                count=cnt,
            )
            for wd, (total, cnt) in sorted(weekday_totals.items())
        ]

        # ── Tag source breakdown ──────────────────────────────────────────────
        source_counts: dict[str, int] = defaultdict(int)
        for t in txs:
            source_counts[t.tag_source] += 1
        report.tag_source_counts = dict(source_counts)

        return report
