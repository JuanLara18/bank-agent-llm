"""Unit tests for the Bancolombia parser (row-level logic, no real PDF)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from bank_agent_llm.parsers.bancolombia import (
    BancolombiaParser, _dedup_installments, _parse_row, _untriple, _extract_card_digits,
)
from bank_agent_llm.parsers.base import RawTransaction, TransactionDirection


# ── can_parse ─────────────────────────────────────────────────────────────────

def test_can_parse_with_signature(tmp_path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = BancolombiaParser()
    assert parser.can_parse(pdf, hint="NIT: 890.903.938-8 VISA 1332") is True


def test_can_parse_without_signature(tmp_path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = BancolombiaParser()
    assert parser.can_parse(pdf, hint="Some Other Bank") is False


def test_can_parse_non_pdf(tmp_path) -> None:
    xlsx = tmp_path / "statement.xlsx"
    xlsx.touch()
    parser = BancolombiaParser()
    assert parser.can_parse(xlsx, hint="890.903.938-8") is False


# ── _parse_row ────────────────────────────────────────────────────────────────

def test_parse_row_debit_without_auth() -> None:
    tokens = ["11/02/2026", "DLO*DIDI", "$", "9.600,00", "1/1", "$", "9.600,00"]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.date == date(2026, 2, 11)
    assert tx.amount == Decimal("9600.00")
    assert tx.direction == TransactionDirection.DEBIT
    assert tx.raw_description == "DLO*DIDI"


def test_parse_row_debit_with_auth_code() -> None:
    tokens = ["023785", "11/02/2026", "NETFLIX", "$", "25.900,00"]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.date == date(2026, 2, 11)
    assert tx.raw_description == "NETFLIX"
    assert tx.direction == TransactionDirection.DEBIT


def test_parse_row_credit_payment() -> None:
    tokens = ["925161", "01/02/2026", "ABONO", "WOMPI/PSE", "$", "-2.085.486,00"]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.direction == TransactionDirection.CREDIT
    assert tx.amount == Decimal("2085486.00")


def test_parse_row_no_date_returns_none() -> None:
    tokens = ["CONCEPTO", "DE", "FACTURACION", "$", "1.000,00"]
    assert _parse_row(tokens, "file.pdf", 0) is None


def test_parse_row_no_dollar_separator_returns_none() -> None:
    tokens = ["01/01/2026", "SOME", "DESCRIPTION"]
    assert _parse_row(tokens, "file.pdf", 0) is None


def test_parse_row_multiword_description() -> None:
    tokens = ["15/03/2026", "TIENDA", "D1", "CALLE", "80", "$", "32.500,00"]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.raw_description == "TIENDA D1 CALLE 80"


def test_parse_row_position_set() -> None:
    tokens = ["11/02/2026", "TEST", "$", "1.000,00"]
    tx = _parse_row(tokens, "file.pdf", 7)
    assert tx is not None
    assert tx.position_in_statement == 7


def test_parse_row_alphanumeric_auth_code() -> None:
    """Auth codes like C07817 or R02013 must be recognized as auth prefixes."""
    tokens = ["C07817", "27/02/2026", "ABONO", "WOMPI/PSE", "$", "-2.000.000,00"]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.direction == TransactionDirection.CREDIT
    assert tx.amount == Decimal("2000000.00")


def test_parse_row_r_prefixed_auth_code() -> None:
    tokens = ["R02013", "24/02/2026", "CURSOR", "USAGE", "$", "103,72"]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.raw_description == "CURSOR USAGE"


# ── Installment rows (Ampliacion de Plazo) ───────────────────────────────────

def test_parse_row_single_installment_unchanged() -> None:
    """1/1 rows (single payment) must not be modified — amount and description stay."""
    tokens = ["11/02/2026", "DLO*DIDI", "$", "9.600,00", "1/1", "$", "9.600,00"]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.amount == Decimal("9600.00")
    assert tx.raw_description == "DLO*DIDI"


def test_parse_row_deferred_uses_monthly_installment() -> None:
    """N/M rows (deferred purchase) must store the cuota mensual, not the total balance."""
    # Mirrors: AMPLIACION DE PLAZO $5.617.637,43  1/12  $468.136,45  ...
    tokens = [
        "000000", "30/10/2025", "AMPLIACION", "DE", "PLAZO",
        "$", "5.617.637,43", "1/12", "$", "468.136,45",
        "1,8312", "%", "24,3283", "%", "$", "5.149.500,98",
    ]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.amount == Decimal("468136.45")
    assert tx.raw_description == "AMPLIACION DE PLAZO 1/12"
    assert tx.direction == TransactionDirection.DEBIT


def test_parse_row_deferred_different_installment_number() -> None:
    """Each installment (e.g. 3/12) gets a unique description hash."""
    tokens = [
        "000000", "30/10/2025", "AMPLIACION", "DE", "PLAZO",
        "$", "5.149.500,98", "3/12", "$", "468.200,00",
        "1,8312", "%", "$", "4.681.300,00",
    ]
    tx = _parse_row(tokens, "file.pdf", 2)
    assert tx is not None
    assert tx.amount == Decimal("468200.00")
    assert tx.raw_description == "AMPLIACION DE PLAZO 3/12"


# ── _untriple ─────────────────────────────────────────────────────────────────

def test_untriple_valid() -> None:
    assert _untriple("111333333222") == "1332"


def test_untriple_non_uniform_group_returns_empty() -> None:
    assert _untriple("112333333222") == ""


def test_untriple_odd_length_returns_empty() -> None:
    assert _untriple("1133") == ""


# ── _extract_card_digits ──────────────────────────────────────────────────────

def test_extract_card_digits_from_triple_encoded_token() -> None:
    tokens = ["***************************111333333222"]
    result = _extract_card_digits(tokens)
    assert result == "1332"


def test_extract_card_digits_mastercard() -> None:
    tokens = ["***000000000000000666777444555"]
    result = _extract_card_digits(tokens)
    assert result == "6745"


def test_extract_card_digits_no_match() -> None:
    tokens = ["NIT:", "890.903.938-8"]
    assert _extract_card_digits(tokens) is None


def test_bank_name() -> None:
    assert BancolombiaParser().bank_name == "Bancolombia"


# ── _dedup_installments ─────────────────────────────────────────────────────

def _raw(desc: str, amount: str = "100000", pos: int = 0) -> RawTransaction:
    return RawTransaction(
        date=date(2025, 12, 2),
        amount=Decimal(amount),
        direction=TransactionDirection.DEBIT,
        raw_description=desc,
        bank_name="Bancolombia",
        source_file="test.pdf",
        position_in_statement=pos,
    )


def test_dedup_installments_removes_total_row() -> None:
    """When an installment version exists, the total-amount row is dropped."""
    txs = [
        _raw("COURSERA.ORG", "109674.50", pos=0),      # total — should be removed
        _raw("COURSERA.ORG 3/36", "3046.51", pos=1),    # installment — kept
    ]
    result = _dedup_installments(txs)
    assert len(result) == 1
    assert result[0].raw_description == "COURSERA.ORG 3/36"


def test_dedup_installments_keeps_non_installment() -> None:
    """Regular purchases without installments are not affected."""
    txs = [
        _raw("UBER EATS", "25000", pos=0),
        _raw("STARBUCKS", "12000", pos=1),
    ]
    result = _dedup_installments(txs)
    assert len(result) == 2


def test_dedup_installments_keeps_unrelated_same_date() -> None:
    """A different merchant on the same date is not confused for a total row."""
    txs = [
        _raw("APPLE.COM/BILL", "4500", pos=0),
        _raw("COURSERA.ORG 3/36", "3046.51", pos=1),
    ]
    result = _dedup_installments(txs)
    assert len(result) == 2


def test_dedup_installments_renumbers_positions() -> None:
    """Positions are re-numbered after dedup to stay sequential."""
    txs = [
        _raw("COURSERA.ORG", "109674.50", pos=0),
        _raw("COURSERA.ORG 3/36", "3046.51", pos=1),
        _raw("UBER EATS", "25000", pos=2),
    ]
    result = _dedup_installments(txs)
    assert len(result) == 2
    assert result[0].position_in_statement == 0
    assert result[1].position_in_statement == 1
