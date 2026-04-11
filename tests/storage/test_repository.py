"""Repository unit tests — run against an in-memory SQLite database."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from bank_agent_llm.storage.models import Account, Base, FileProcessingRun, Transaction
from bank_agent_llm.storage.repository import (
    AccountRepository,
    CategoryRepository,
    FileProcessingRunRepository,
    PipelineRunRepository,
    TransactionRepository,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s


def _make_account(session: Session, bank: str = "TestBank") -> Account:
    repo = AccountRepository(session)
    return repo.get_or_create(bank_name=bank, account_number="ACC-001")


def _make_transaction(account: Account, pos: int = 0, amount: str = "50000.00") -> Transaction:
    desc = "COMPRA POS TIENDA"
    return Transaction(
        account_id=account.id,
        date=date(2026, 1, 15),
        amount=Decimal(amount),
        currency="COP",
        direction="debit",
        raw_description=desc,
        source_file="statement.pdf",
        description_hash=hashlib.sha256(desc.encode()).hexdigest(),
        position_in_statement=pos,
    )


# ─── AccountRepository ────────────────────────────────────────────────────────

def test_get_or_create_creates_new_account(session: Session) -> None:
    repo = AccountRepository(session)
    account = repo.get_or_create("Bancolombia", "123456789")
    assert account.id is not None
    assert account.bank_name == "Bancolombia"


def test_get_or_create_returns_existing(session: Session) -> None:
    repo = AccountRepository(session)
    a1 = repo.get_or_create("Bancolombia", "123456789")
    a2 = repo.get_or_create("Bancolombia", "123456789")
    assert a1.id == a2.id


def test_get_or_create_different_accounts(session: Session) -> None:
    repo = AccountRepository(session)
    a1 = repo.get_or_create("BankA", "ACC-001")
    a2 = repo.get_or_create("BankB", "ACC-002")
    assert a1.id != a2.id
    assert len(repo.all()) == 2


# ─── CategoryRepository ──────────────────────────────────────────────────────

def test_get_or_create_category(session: Session) -> None:
    repo = CategoryRepository(session)
    cat = repo.get_or_create("Food & Dining")
    assert cat.id is not None
    assert repo.get_or_create("Food & Dining").id == cat.id


def test_category_with_parent(session: Session) -> None:
    repo = CategoryRepository(session)
    parent = repo.get_or_create("Food & Dining")
    child = repo.get_or_create("Restaurants", parent_id=parent.id)
    assert child.parent_id == parent.id


# ─── TransactionRepository ───────────────────────────────────────────────────

def test_add_transaction(session: Session) -> None:
    account = _make_account(session)
    session.commit()
    repo = TransactionRepository(session)
    tx, created = repo.add_or_skip(_make_transaction(account))
    assert created is True
    assert tx.id is not None


def test_add_or_skip_returns_false_for_duplicate(session: Session) -> None:
    account = _make_account(session)
    session.commit()
    repo = TransactionRepository(session)
    tx1 = _make_transaction(account, pos=0)
    _, created1 = repo.add_or_skip(tx1)
    tx2 = _make_transaction(account, pos=0)  # same position = duplicate
    _, created2 = repo.add_or_skip(tx2)
    assert created1 is True
    assert created2 is False
    assert repo.count() == 1


def test_same_amount_different_position_creates_two(session: Session) -> None:
    """Two identical coffees on the same day must both be stored."""
    account = _make_account(session)
    session.commit()
    repo = TransactionRepository(session)
    _, c1 = repo.add_or_skip(_make_transaction(account, pos=0))
    _, c2 = repo.add_or_skip(_make_transaction(account, pos=1))
    assert c1 is True
    assert c2 is True
    assert repo.count() == 2


def test_find_by_account(session: Session) -> None:
    account = _make_account(session)
    session.commit()
    repo = TransactionRepository(session)
    repo.add_or_skip(_make_transaction(account, pos=0))
    repo.add_or_skip(_make_transaction(account, pos=1))
    results = repo.find_by_account(account.id)
    assert len(results) == 2


def test_find_uncategorized(session: Session) -> None:
    account = _make_account(session)
    session.commit()
    repo = TransactionRepository(session)
    repo.add_or_skip(_make_transaction(account, pos=0))
    assert len(repo.find_uncategorized()) == 1


def test_delete_before(session: Session) -> None:
    account = _make_account(session)
    session.commit()
    repo = TransactionRepository(session)
    repo.add_or_skip(_make_transaction(account, pos=0))  # 2026-01-15
    deleted = repo.delete_before(date(2026, 2, 1))
    assert deleted == 1
    assert repo.count() == 0


# ─── FileProcessingRunRepository ─────────────────────────────────────────────

def test_file_not_processed_initially(session: Session) -> None:
    repo = FileProcessingRunRepository(session)
    assert repo.is_processed("abc123") is False


def test_mark_file_processed(session: Session) -> None:
    repo = FileProcessingRunRepository(session)
    repo.create("statement.pdf", "abc123", "success", bank_name="TestBank", transaction_count=5)
    assert repo.is_processed("abc123") is True


def test_errored_file_not_considered_processed(session: Session) -> None:
    repo = FileProcessingRunRepository(session)
    repo.create("bad.pdf", "def456", "error", error_message="parse failed")
    assert repo.is_processed("def456") is False


def test_skipped_file_is_retried_on_next_run(session: Session) -> None:
    """A file previously marked 'skipped' must be retried so that parser fixes
    automatically pick up previously-dropped statements."""
    repo = FileProcessingRunRepository(session)
    repo.create("unknown.pdf", "ghi789", "skipped", error_message="no parser matched")
    assert repo.is_processed("ghi789") is False


def test_record_outcome_upserts_by_hash(session: Session) -> None:
    """record_outcome updates the existing row for a hash instead of raising
    on the unique constraint — so a retry after a parser fix overwrites the
    previous 'skipped' outcome."""
    repo = FileProcessingRunRepository(session)
    repo.record_outcome("old.pdf", "hash1", "skipped", error_message="no parser matched")
    repo.record_outcome(
        "new.pdf", "hash1", "success",
        bank_name="TestBank", transaction_count=42,
    )
    assert repo.is_processed("hash1") is True
    rows = list(session.execute(select(FileProcessingRun).where(
        FileProcessingRun.file_hash == "hash1"
    )).scalars())
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].bank_name == "TestBank"
    assert rows[0].transaction_count == 42
    assert rows[0].error_message is None
    assert rows[0].file_path == "new.pdf"


# ─── PipelineRunRepository ────────────────────────────────────────────────────

def test_pipeline_run_lifecycle(session: Session) -> None:
    repo = PipelineRunRepository(session)
    run = repo.start()
    assert run.status == "running"
    repo.finish(run, "success", stages_completed=["fetch", "parse"], parsed=10, enriched=10)
    latest = repo.latest()
    assert latest is not None
    assert latest.status == "success"
    assert latest.transactions_parsed == 10
