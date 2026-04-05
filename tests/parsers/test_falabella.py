"""Unit tests for the Falabella CMR parser (row-level logic, no real PDF)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from bank_agent_llm.parsers.falabella import FalabellaParser, _parse_row
from bank_agent_llm.parsers.base import TransactionDirection


# ── can_parse ─────────────────────────────────────────────────────────────────

def test_can_parse_cmr_signature(tmp_path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = FalabellaParser()
    assert parser.can_parse(pdf, hint="Tarjeta de Crédito CMR Banco Falabella") is True


def test_can_parse_banco_falabella(tmp_path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = FalabellaParser()
    assert parser.can_parse(pdf, hint="BANCO FALABELLA COLOMBIA") is True


def test_can_parse_no_signature(tmp_path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = FalabellaParser()
    assert parser.can_parse(pdf, hint="890.903.938-8") is False


def test_can_parse_non_pdf(tmp_path) -> None:
    xlsx = tmp_path / "statement.xlsx"
    xlsx.touch()
    parser = FalabellaParser()
    assert parser.can_parse(xlsx, hint="CMR") is False


# ── _parse_row ────────────────────────────────────────────────────────────────

def test_parse_row_debit_purchase() -> None:
    # 01/02/2026 LA CHULA 116 AVC 116 19-50 TT $54.630,00 2 de 24 $0,00
    tokens = ["01/02/2026", "LA", "CHULA", "116", "AVC", "TT", "$54.630,00", "2", "de", "24"]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.date == date(2026, 2, 1)
    assert tx.amount == Decimal("54630.00")
    assert tx.direction == TransactionDirection.DEBIT
    assert "LA" in tx.raw_description


def test_parse_row_credit_payment() -> None:
    # 27/02/2026 PAGO TARJETA CMR TT --$944.714,94
    tokens = ["27/02/2026", "PAGO", "TARJETA", "CMR", "TT", "--$944.714,94"]
    tx = _parse_row(tokens, "file.pdf", 0)
    assert tx is not None
    assert tx.direction == TransactionDirection.CREDIT
    assert tx.amount == Decimal("944714.94")


def test_parse_row_no_tt_returns_none() -> None:
    tokens = ["01/01/2026", "DESCRIPTION", "$100.000,00"]
    assert _parse_row(tokens, "file.pdf", 0) is None


def test_parse_row_no_date_returns_none() -> None:
    tokens = ["CONCEPTO", "TT", "$1.000,00"]
    assert _parse_row(tokens, "file.pdf", 0) is None


def test_parse_row_too_short_returns_none() -> None:
    assert _parse_row(["01/01/2026"], "file.pdf", 0) is None


def test_parse_row_position_set() -> None:
    tokens = ["15/03/2026", "NETFLIX", "TT", "$19.900,00"]
    tx = _parse_row(tokens, "file.pdf", 5)
    assert tx is not None
    assert tx.position_in_statement == 5


def test_bank_name() -> None:
    assert FalabellaParser().bank_name == "Falabella CMR"
