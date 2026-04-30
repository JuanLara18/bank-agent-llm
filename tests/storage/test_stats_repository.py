"""Unit tests for StatsRepository — aggregation logic for the status dashboard."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from bank_agent_llm.storage.models import Account, Base, Transaction
from bank_agent_llm.storage.repository import StatsRepository

# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s


def _add_account(session: Session, bank: str, suffix: str) -> Account:
    acc = Account(
        bank_name=bank,
        account_number_hash=hashlib.sha256(suffix.encode()).hexdigest(),
        currency="COP",
    )
    session.add(acc)
    session.flush()
    return acc


def _add_tx(
    session: Session,
    account: Account,
    *,
    tx_date: date,
    amount: str,
    direction: str,
    description: str = "COMPRA",
    tags: list[str] | None = None,
    tag_source: str = "keyword_rule",
    merchant: str | None = None,
    pos: int = 0,
) -> Transaction:
    tx = Transaction(
        account_id=account.id,
        date=tx_date,
        amount=Decimal(amount),
        currency="COP",
        direction=direction,
        raw_description=description,
        source_file="statement.pdf",
        description_hash=hashlib.sha256(description.encode()).hexdigest(),
        position_in_statement=pos,
        tags=tags or [],
        tag_source=tag_source,
        merchant_name=merchant,
    )
    session.add(tx)
    session.flush()
    return tx


# ─── all_transactions ─────────────────────────────────────────────────────────

def test_all_transactions_returns_empty_on_empty_db(session: Session) -> None:
    assert StatsRepository(session).all_transactions() == []


def test_all_transactions_filters_by_date_range(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    _add_tx(session, acc, tx_date=date(2026, 1, 10), amount="100", direction="debit", pos=0)
    _add_tx(session, acc, tx_date=date(2026, 2, 10), amount="200", direction="debit", pos=1)
    _add_tx(session, acc, tx_date=date(2026, 3, 10), amount="300", direction="debit", pos=2)

    repo = StatsRepository(session)
    result = repo.all_transactions(
        date_from=date(2026, 2, 1), date_to=date(2026, 2, 28)
    )
    assert len(result) == 1
    assert result[0].amount == Decimal("200")


def test_all_transactions_filters_by_account(session: Session) -> None:
    a1 = _add_account(session, "BankA", "001")
    a2 = _add_account(session, "BankB", "002")
    _add_tx(session, a1, tx_date=date(2026, 1, 1), amount="100", direction="debit", pos=0)
    _add_tx(session, a2, tx_date=date(2026, 1, 1), amount="200", direction="debit", pos=0)

    result = StatsRepository(session).all_transactions(account_ids=[a1.id])
    assert len(result) == 1
    assert result[0].account_id == a1.id


def test_all_transactions_excludes_cancelled_when_requested(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    _add_tx(
        session, acc,
        tx_date=date(2026, 1, 1), amount="100", direction="debit",
        tags=["restaurante"], pos=0,
    )
    _add_tx(
        session, acc,
        tx_date=date(2026, 1, 2), amount="200", direction="debit",
        tags=["cancelada"], pos=1,
    )

    repo = StatsRepository(session)
    assert len(repo.all_transactions(include_cancelled=True)) == 2
    assert len(repo.all_transactions(include_cancelled=False)) == 1


# ─── build_report: empty state ────────────────────────────────────────────────

def test_build_report_empty_db(session: Session) -> None:
    report = StatsRepository(session).build_report()
    assert report.total_transactions == 0
    assert report.pending_enrichment == 0
    assert report.total_debit == Decimal("0")
    assert report.total_credit == Decimal("0")
    assert report.accounts == []
    assert report.monthly == []


# ─── build_report: totals and debit/credit split ──────────────────────────────

def test_build_report_totals(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    _add_tx(session, acc, tx_date=date(2026, 1, 1), amount="1000", direction="debit",
            tags=["restaurante"], pos=0)
    _add_tx(session, acc, tx_date=date(2026, 1, 2), amount="500", direction="debit",
            tags=["supermercado"], pos=1)
    _add_tx(session, acc, tx_date=date(2026, 1, 3), amount="3000", direction="credit",
            tags=["salario"], pos=2)

    report = StatsRepository(session).build_report()
    assert report.total_transactions == 3
    assert report.total_debit == Decimal("1500")
    assert report.total_credit == Decimal("3000")
    assert report.date_min == date(2026, 1, 1)
    assert report.date_max == date(2026, 1, 3)


def test_build_report_pending_counted(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    _add_tx(session, acc, tx_date=date(2026, 1, 1), amount="100", direction="debit",
            tag_source="pending", pos=0)
    _add_tx(session, acc, tx_date=date(2026, 1, 2), amount="100", direction="debit",
            tags=["restaurante"], tag_source="keyword_rule", pos=1)

    report = StatsRepository(session).build_report()
    assert report.pending_enrichment == 1


# ─── build_report: per-account summary ────────────────────────────────────────

def test_build_report_account_summaries(session: Session) -> None:
    a1 = _add_account(session, "BankA", "001")
    a2 = _add_account(session, "BankB", "002")
    _add_tx(session, a1, tx_date=date(2026, 1, 1), amount="100", direction="debit",
            tags=["restaurante"], pos=0)
    _add_tx(session, a1, tx_date=date(2026, 1, 5), amount="50", direction="credit",
            tags=["salario"], pos=1)
    _add_tx(session, a2, tx_date=date(2026, 1, 2), amount="200", direction="debit",
            tags=["restaurante"], pos=0)

    report = StatsRepository(session).build_report()
    assert len(report.accounts) == 2
    by_bank = {a.bank_name: a for a in report.accounts}
    assert by_bank["BankA"].total == 2
    assert by_bank["BankA"].total_debit == Decimal("100")
    assert by_bank["BankA"].total_credit == Decimal("50")
    assert by_bank["BankB"].total == 1
    assert by_bank["BankB"].total_debit == Decimal("200")


def test_build_report_skips_account_with_no_tx(session: Session) -> None:
    _add_account(session, "BankA", "001")  # no tx
    a2 = _add_account(session, "BankB", "002")
    _add_tx(session, a2, tx_date=date(2026, 1, 1), amount="100", direction="debit",
            tags=["restaurante"], pos=0)

    report = StatsRepository(session).build_report()
    assert len(report.accounts) == 1
    assert report.accounts[0].bank_name == "BankB"


# ─── build_report: monthly ────────────────────────────────────────────────────

def test_build_report_monthly_buckets(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    _add_tx(session, acc, tx_date=date(2026, 1, 15), amount="100", direction="debit",
            tags=["restaurante"], pos=0)
    _add_tx(session, acc, tx_date=date(2026, 1, 20), amount="50", direction="debit",
            tags=["restaurante"], pos=1)
    _add_tx(session, acc, tx_date=date(2026, 2, 5), amount="300", direction="debit",
            tags=["restaurante"], pos=2)

    report = StatsRepository(session).build_report()
    assert len(report.monthly) == 2
    jan, feb = report.monthly
    assert (jan.year, jan.month, jan.debit) == (2026, 1, Decimal("150"))
    assert (feb.year, feb.month, feb.debit) == (2026, 2, Decimal("300"))
    assert jan.label == "Jan 2026"


# ─── build_report: top tags (expense debits, primary tag) ────────────────────

def test_build_report_top_tags_uses_primary_expense_tag(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    # Leaf tag present → primary_tag returns "restaurante" (under comida)
    _add_tx(session, acc, tx_date=date(2026, 1, 1), amount="500", direction="debit",
            tags=["restaurante"], pos=0)
    _add_tx(session, acc, tx_date=date(2026, 1, 2), amount="300", direction="debit",
            tags=["supermercado"], pos=1)
    _add_tx(session, acc, tx_date=date(2026, 1, 3), amount="200", direction="debit",
            tags=["restaurante"], pos=2)

    report = StatsRepository(session).build_report()
    by_tag = {t.tag: t for t in report.top_tags}
    assert by_tag["restaurante"].total == Decimal("700")
    assert by_tag["restaurante"].count == 2
    assert by_tag["supermercado"].total == Decimal("300")


def test_build_report_top_tags_excludes_pending_and_credits(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    _add_tx(session, acc, tx_date=date(2026, 1, 1), amount="100", direction="debit",
            tags=["restaurante"], tag_source="pending", pos=0)
    _add_tx(session, acc, tx_date=date(2026, 1, 2), amount="2000", direction="credit",
            tags=["restaurante"], pos=1)
    _add_tx(session, acc, tx_date=date(2026, 1, 3), amount="50", direction="debit",
            tags=["restaurante"], pos=2)

    report = StatsRepository(session).build_report()
    # Only the 50 debit (non-pending) should be in the totals
    by_tag = {t.tag: t for t in report.top_tags}
    assert by_tag["restaurante"].total == Decimal("50")
    assert by_tag["restaurante"].count == 1


# ─── build_report: top merchants ──────────────────────────────────────────────

def test_build_report_top_merchants_aggregates_by_name(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    _add_tx(session, acc, tx_date=date(2026, 1, 1), amount="30", direction="debit",
            tags=["restaurante"], merchant="Juan Valdez",
            description="JUAN VALDEZ CC", pos=0)
    _add_tx(session, acc, tx_date=date(2026, 1, 2), amount="45", direction="debit",
            tags=["restaurante"], merchant="Juan Valdez",
            description="JUAN VALDEZ ANDINO", pos=1)
    _add_tx(session, acc, tx_date=date(2026, 1, 3), amount="100", direction="debit",
            tags=["supermercado"], merchant="Éxito",
            description="EXITO 123", pos=2)

    report = StatsRepository(session).build_report()
    by_m = {m.merchant: m for m in report.top_merchants}
    assert by_m["Juan Valdez"].total == Decimal("75")
    assert by_m["Juan Valdez"].count == 2
    assert by_m["Éxito"].total == Decimal("100")


def test_build_report_top_merchants_normalizes_casing(session: Session) -> None:
    """LLM variants like 'NEQUI' and 'Nequi' must group into one merchant."""
    acc = _add_account(session, "BankA", "001")
    _add_tx(session, acc, tx_date=date(2026, 1, 1), amount="20", direction="debit",
            tags=["comida", "restaurante"], merchant="NEQUI",
            description="TRANSF QR NEQUI AAA", pos=0)
    _add_tx(session, acc, tx_date=date(2026, 1, 2), amount="30", direction="debit",
            tags=["comida", "restaurante"], merchant="Nequi",
            description="TRANSF QR NEQUI BBB", pos=1)

    report = StatsRepository(session).build_report()
    # Both should be grouped into a single merchant entry
    assert len(report.top_merchants) == 1
    assert report.top_merchants[0].total == Decimal("50")
    assert report.top_merchants[0].count == 2


def test_build_report_merchant_fallback_to_raw_description(session: Session) -> None:
    """When merchant_name is NULL, the raw description (truncated) is used."""
    acc = _add_account(session, "BankA", "001")
    _add_tx(session, acc, tx_date=date(2026, 1, 1), amount="100", direction="debit",
            tags=["restaurante"], merchant=None, description="SOME RAW POS 123", pos=0)

    report = StatsRepository(session).build_report()
    assert len(report.top_merchants) == 1
    assert report.top_merchants[0].merchant.startswith("SOME RAW POS")


# ─── build_report: weekday breakdown ──────────────────────────────────────────

def test_build_report_weekday_breakdown(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    # 2026-01-05 is Monday (weekday 0); 2026-01-07 is Wednesday (weekday 2)
    _add_tx(session, acc, tx_date=date(2026, 1, 5), amount="100", direction="debit",
            tags=["restaurante"], pos=0)
    _add_tx(session, acc, tx_date=date(2026, 1, 7), amount="200", direction="debit",
            tags=["restaurante"], pos=1)
    _add_tx(session, acc, tx_date=date(2026, 1, 12), amount="300", direction="debit",
            tags=["restaurante"], pos=2)  # Monday again

    report = StatsRepository(session).build_report()
    by_wd = {d.weekday: d for d in report.by_weekday}
    assert by_wd[0].total == Decimal("400")  # Monday (100 + 300)
    assert by_wd[0].count == 2
    assert by_wd[0].label == "Lunes"
    assert by_wd[2].total == Decimal("200")  # Wednesday
    assert by_wd[2].label == "Miércoles"


# ─── build_report: tag source breakdown ───────────────────────────────────────

def test_build_report_tag_source_counts(session: Session) -> None:
    acc = _add_account(session, "BankA", "001")
    _add_tx(session, acc, tx_date=date(2026, 1, 1), amount="100", direction="debit",
            tag_source="keyword_rule", tags=["restaurante"], pos=0)
    _add_tx(session, acc, tx_date=date(2026, 1, 2), amount="100", direction="debit",
            tag_source="keyword_rule", tags=["restaurante"], pos=1)
    _add_tx(session, acc, tx_date=date(2026, 1, 3), amount="100", direction="debit",
            tag_source="llm", tags=["restaurante"], pos=2)
    _add_tx(session, acc, tx_date=date(2026, 1, 4), amount="100", direction="debit",
            tag_source="pending", pos=3)

    report = StatsRepository(session).build_report()
    assert report.tag_source_counts == {
        "keyword_rule": 2,
        "llm": 1,
        "pending": 1,
    }
