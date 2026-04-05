"""Unit tests for the Bancolombia parser (row-level logic, no real PDF)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from bank_agent_llm.parsers.bancolombia import BancolombiaParser, _parse_row, _untriple, _extract_card_digits
from bank_agent_llm.parsers.base import TransactionDirection


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
