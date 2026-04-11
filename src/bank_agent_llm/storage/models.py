"""SQLAlchemy models.

All schema changes must go through Alembic migrations — never alter tables
directly. Run ``bank-agent db migrate`` to apply pending migrations.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Account(Base):
    """One row per bank account tracked."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_number_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    owner_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="COP")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )


class Transaction(Base):
    """One row per transaction.

    Unique constraint on (account_id, date, amount, description_hash,
    position_in_statement) prevents duplicates while handling same-day
    identical transactions via position_in_statement.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "date",
            "amount",
            "description_hash",
            "position_in_statement",
            name="uq_transaction_dedup",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="COP")
    direction: Mapped[str] = mapped_column(String(6), nullable=False)  # debit | credit
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[str] = mapped_column(Text, nullable=False)
    description_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    position_in_statement: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Enrichment fields — populated by bank-agent enrich
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tag_source: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    merchant_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    account: Mapped[Account] = relationship("Account", back_populates="transactions")


class ProcessedEmail(Base):
    """Registry of fetched emails — prevents re-downloading on subsequent runs."""

    __tablename__ = "processed_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_account: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class FileProcessingRun(Base):
    """Tracks each statement file processed — enables idempotent re-runs."""

    __tablename__ = "file_processing_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success | error | skipped
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        primaryjoin="foreign(Transaction.source_file) == FileProcessingRun.file_path",
        viewonly=True,
    )


class MerchantCache(Base):
    """Cache of Ollama-assigned tags per merchant key.

    Avoids calling Ollama twice for the same merchant description.
    ``merchant_key`` is the normalized (uppercased, stripped) raw_description.
    """

    __tablename__ = "merchant_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False)
    merchant_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # llm | manual
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class PipelineRun(Base):
    """Tracks each full pipeline execution for status reporting."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # running | success | error
    stages_completed: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    transactions_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transactions_parsed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transactions_enriched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
