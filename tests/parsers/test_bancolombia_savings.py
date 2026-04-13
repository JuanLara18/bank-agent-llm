"""Unit tests for the Bancolombia savings account parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bank_agent_llm.parsers.bancolombia_savings import (
    BancolombiaSavingsParser,
    _parse_us_amount,
)
from bank_agent_llm.parsers.base import ParseError, TransactionDirection

# ── can_parse ────────────────────────────────────────────────────────────────

def test_can_parse_with_both_signatures(tmp_path: Path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = BancolombiaSavingsParser()
    hint = "ESTADO DE CUENTA\nCUENTA DE AHORROS\nDESDE: 2025/01/01"
    assert parser.can_parse(pdf, hint=hint) is True


def test_can_parse_missing_product_signature(tmp_path: Path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = BancolombiaSavingsParser()
    # Credit card statement — has "ESTADO DE CUENTA" but not savings layout
    assert parser.can_parse(pdf, hint="ESTADO DE CUENTA TARJETA DE CREDITO") is False


def test_can_parse_missing_statement_signature(tmp_path: Path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    parser = BancolombiaSavingsParser()
    assert parser.can_parse(pdf, hint="CUENTA DE AHORROS") is False


def test_can_parse_non_pdf(tmp_path: Path) -> None:
    xlsx = tmp_path / "statement.xlsx"
    xlsx.touch()
    parser = BancolombiaSavingsParser()
    hint = "ESTADO DE CUENTA CUENTA DE AHORROS"
    assert parser.can_parse(xlsx, hint=hint) is False


# ── _parse_us_amount ─────────────────────────────────────────────────────────

def test_parse_us_amount_positive() -> None:
    assert _parse_us_amount("3,708,833.17") == Decimal("3708833.17")


def test_parse_us_amount_negative() -> None:
    assert _parse_us_amount("-172,000.00") == Decimal("-172000.00")


def test_parse_us_amount_small_negative() -> None:
    assert _parse_us_amount("-.01") == Decimal("-0.01")


def test_parse_us_amount_invalid() -> None:
    with pytest.raises(ValueError):
        _parse_us_amount("not-a-number")


# ── parse() ──────────────────────────────────────────────────────────────────

_SAMPLE_TEXT = """ESTADO DE CUENTA
CUENTA DE AHORROS
NÚMERO 54743816610
DESDE: 2025/01/01 HASTA: 2025/03/31
FECHA DESCRIPCIÓN SUCURSAL DCTO. VALOR SALDO
1/01 ABONO INTERESES AHORROS 3.00 3,708,833.17
2/01 TRANSFERENCIA A NEQUI -172,000.00 3,536,833.17
15/02 PAGO NOMINA EMPRESA SA 2,500,000.00 6,036,833.17
28/03 COMPRA POS TIENDA XYZ -45,500.50 5,991,332.67
"""


def _mock_pdfplumber(text: str) -> MagicMock:
    fake_page = MagicMock()
    fake_page.extract_text.return_value = text
    fake_pdf = MagicMock()
    fake_pdf.pages = [fake_page]
    ctx = MagicMock()
    ctx.__enter__.return_value = fake_pdf
    ctx.__exit__.return_value = False
    return ctx


def test_parse_extracts_transactions(tmp_path: Path) -> None:
    pdf = tmp_path / "savings.pdf"
    pdf.touch()
    parser = BancolombiaSavingsParser()
    with patch(
        "bank_agent_llm.parsers.bancolombia_savings.open_pdf",
        return_value=_mock_pdfplumber(_SAMPLE_TEXT),
    ):
        txs = parser.parse(pdf)

    assert len(txs) == 4
    assert txs[0].date == date(2025, 1, 1)
    assert txs[0].amount == Decimal("3.00")
    assert txs[0].direction == TransactionDirection.CREDIT
    assert "INTERESES" in txs[0].raw_description

    assert txs[1].date == date(2025, 1, 2)
    assert txs[1].amount == Decimal("172000.00")
    assert txs[1].direction == TransactionDirection.DEBIT

    assert txs[2].direction == TransactionDirection.CREDIT
    assert txs[2].amount == Decimal("2500000.00")
    assert txs[3].amount == Decimal("45500.50")
    assert txs[3].direction == TransactionDirection.DEBIT

    # Last 4 digits of account number
    assert txs[0].account_number == "6610"
    # Position preserved
    assert [t.position_in_statement for t in txs] == [0, 1, 2, 3]


def test_parse_year_inference_cross_calendar(tmp_path: Path) -> None:
    """Period spanning a year boundary: the first row (1/01) must pick the
    end-year because 2024-01-01 falls outside [2024-12-31, 2025-03-31]."""
    pdf = tmp_path / "savings.pdf"
    pdf.touch()
    text = """ESTADO DE CUENTA
CUENTA DE AHORROS
DESDE: 2024/12/31 HASTA: 2025/03/31
31/12 SALDO INICIAL 1.00 1,000,000.00
1/01 ABONO INTERESES 2.00 1,000,002.00
15/03 RETIRO ATM -50,000.00 950,002.00
"""
    parser = BancolombiaSavingsParser()
    with patch(
        "bank_agent_llm.parsers.bancolombia_savings.open_pdf",
        return_value=_mock_pdfplumber(text),
    ):
        txs = parser.parse(pdf)

    assert len(txs) == 3
    assert txs[0].date == date(2024, 12, 31)
    assert txs[1].date == date(2025, 1, 1)  # not 2024-01-01
    assert txs[2].date == date(2025, 3, 15)


def test_parse_raises_when_period_missing(tmp_path: Path) -> None:
    pdf = tmp_path / "savings.pdf"
    pdf.touch()
    text = "ESTADO DE CUENTA\nCUENTA DE AHORROS\n1/01 SOMETHING 1.00 1.00\n"
    parser = BancolombiaSavingsParser()
    with patch(
        "bank_agent_llm.parsers.bancolombia_savings.open_pdf",
        return_value=_mock_pdfplumber(text),
    ), pytest.raises(ParseError, match="statement period"):
        parser.parse(pdf)


def test_parse_skips_non_matching_lines(tmp_path: Path) -> None:
    """Header, footer and blank lines must not produce transactions."""
    pdf = tmp_path / "savings.pdf"
    pdf.touch()
    text = """ESTADO DE CUENTA
CUENTA DE AHORROS
DESDE: 2025/01/01 HASTA: 2025/03/31
FECHA DESCRIPCIÓN SUCURSAL DCTO. VALOR SALDO

Pagina 1 de 5
1/01 ABONO INTERESES 3.00 3,708,833.17
bancolombia.com footer text here
"""
    parser = BancolombiaSavingsParser()
    with patch(
        "bank_agent_llm.parsers.bancolombia_savings.open_pdf",
        return_value=_mock_pdfplumber(text),
    ):
        txs = parser.parse(pdf)
    assert len(txs) == 1
    assert txs[0].raw_description.startswith("ABONO INTERESES")
