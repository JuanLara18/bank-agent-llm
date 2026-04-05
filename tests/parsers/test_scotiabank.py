"""Unit tests for the Scotiabank Colpatria parser (row-level logic, no real PDF)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from bank_agent_llm.parsers.scotiabank import ScotiabankParser, _parse_row
from bank_agent_llm.parsers.base import TransactionDirection


# ── can_parse ─────────────────────────────────────────────────────────────────

def test_can_parse_with_domain(tmp_path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = ScotiabankParser()
    assert parser.can_parse(pdf, hint="scotiabankcolpatria.com Puntos Cencosud") is True


def test_can_parse_puntos_cencosud(tmp_path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = ScotiabankParser()
    assert parser.can_parse(pdf, hint="Puntos Cencosud") is True


def test_can_parse_no_signature(tmp_path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = ScotiabankParser()
    assert parser.can_parse(pdf, hint="890.903.938-8") is False


def test_can_parse_non_pdf(tmp_path) -> None:
    xlsx = tmp_path / "statement.xlsx"
    xlsx.touch()
    parser = ScotiabankParser()
    assert parser.can_parse(xlsx, hint="scotiabankcolpatria.com") is False


# ── _parse_row ────────────────────────────────────────────────────────────────

def test_parse_row_debit_with_comprobante() -> None:
    # 26/03/2026 181851 ALITAS PAYA Y MEXICAN F $ 41.193 1/1 $ 41.193 $ 0 1,89% 25,25%
    tokens = ["26/03/2026", "181851", "ALITAS", "PAYA", "Y", "MEXICAN", "F",
               "$", "41.193", "1/1", "$", "41.193", "$", "0", "1,89%", "25,25%"]
    tx = _parse_row(tokens, "file.pdf", 0, TransactionDirection.DEBIT)
    assert tx is not None
    assert tx.date == date(2026, 3, 26)
    assert tx.amount == Decimal("41193")
    assert tx.direction == TransactionDirection.DEBIT
    assert tx.reference == "181851"
    assert "ALITAS" in tx.raw_description


def test_parse_row_credit_payment() -> None:
    tokens = ["15/03/2026", "987654", "PAGO", "PSE", "$", "500.000", "1/1"]
    tx = _parse_row(tokens, "file.pdf", 0, TransactionDirection.CREDIT)
    assert tx is not None
    assert tx.direction == TransactionDirection.CREDIT
    assert tx.amount == Decimal("500000")


def test_parse_row_no_date_returns_none() -> None:
    tokens = ["DESCRIPCION", "$", "10.000"]
    assert _parse_row(tokens, "file.pdf", 0, TransactionDirection.DEBIT) is None


def test_parse_row_no_dollar_separator_returns_none() -> None:
    tokens = ["01/01/2026", "181851", "DESCRIPTION", "NO", "DOLLAR"]
    assert _parse_row(tokens, "file.pdf", 0, TransactionDirection.DEBIT) is None


def test_parse_row_zero_amount_returns_none() -> None:
    tokens = ["01/01/2026", "SOME", "ITEM", "$", "0"]
    assert _parse_row(tokens, "file.pdf", 0, TransactionDirection.DEBIT) is None


def test_parse_row_without_comprobante() -> None:
    tokens = ["10/02/2026", "RAPPI", "COLOMBIA", "$", "35.000"]
    tx = _parse_row(tokens, "file.pdf", 0, TransactionDirection.DEBIT)
    assert tx is not None
    assert tx.reference is None
    assert tx.raw_description == "RAPPI COLOMBIA"


def test_parse_row_position_set() -> None:
    tokens = ["10/02/2026", "SHOP", "$", "20.000"]
    tx = _parse_row(tokens, "file.pdf", 3, TransactionDirection.DEBIT)
    assert tx is not None
    assert tx.position_in_statement == 3


def test_bank_name() -> None:
    assert ScotiabankParser().bank_name == "Scotiabank Colpatria"
