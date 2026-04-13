"""Bancolombia savings account statement parser.

Handles password-protected savings account PDFs. Layout is line-oriented:

    FECHA DESCRIPCIÓN SUCURSAL DCTO. VALOR SALDO
    1/01 ABONO INTERESES AHORROS 3.00 3,708,833.17
    2/01 TRANSFERENCIA A NEQUI -172,000.00 2,019,557.17

Each transaction row has a date (D/MM — no year), a free-form description,
an amount and a running balance. Amounts are US-formatted (comma thousands,
period decimal). Negative amounts are debits; positive are credits.

The calendar year is not present on transaction rows, so we infer it from
the statement period header (``DESDE: YYYY/MM/DD HASTA: YYYY/MM/DD``) and
advance it whenever the month decreases (calendar rollover).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bank_agent_llm.parsers._utils import open_pdf
from bank_agent_llm.parsers.base import BankParser, ParseError, RawTransaction, TransactionDirection

_BANK_NAME = "Bancolombia"

# Detection signatures — both must be present in the hint. The pair is
# specific to Bancolombia's savings layout as of 2024–2025; the domain
# string "bancolombia.com" is not used because it lives in the footer and
# can be pushed past the first page on long statements.
_SIG_STATEMENT = "ESTADO DE CUENTA"
_SIG_PRODUCT = "CUENTA DE AHORROS"

# Statement period header: "DESDE: 2024/12/31 HASTA: 2025/03/31"
_PERIOD_RE = re.compile(
    r"DESDE:\s*(\d{4})/(\d{2})/(\d{2})\s+HASTA:\s*(\d{4})/(\d{2})/(\d{2})"
)

# Transaction row — anchored to the end so the last two numeric tokens are
# always captured as amount and balance (description may contain numbers).
# Numeric format: optional sign, US thousands, optional decimal (-.01 valid).
_ROW_RE = re.compile(
    r"^(\d{1,2}/\d{1,2})\s+(.+?)\s+(-?[\d,]*\.?\d+)\s+(-?[\d,]*\.?\d+)\s*$"
)

# Account number label: header has "NÚMERO 54743816610" but the Ñ may be
# mangled by pdfplumber to a replacement char, so allow any single char.
_ACCOUNT_RE = re.compile(r"N.MERO\s+(\d+)")


def _parse_us_amount(text: str) -> Decimal:
    """Parse a US-formatted numeric token (e.g. ``-1,517,276.00`` or ``-.01``)."""
    cleaned = text.replace(",", "").strip()
    if cleaned.startswith("-."):
        cleaned = "-0." + cleaned[2:]
    elif cleaned.startswith("."):
        cleaned = "0" + cleaned
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse amount: {text!r}") from exc


class BancolombiaSavingsParser(BankParser):
    """Parser for Bancolombia savings account PDF statements."""

    def __init__(self, passwords: list[str] | None = None) -> None:
        self._passwords = passwords or []

    @property
    def bank_name(self) -> str:
        return _BANK_NAME

    def can_parse(self, file_path: Path, *, hint: str = "") -> bool:
        if file_path.suffix.lower() != ".pdf":
            return False
        return _SIG_STATEMENT in hint and _SIG_PRODUCT in hint

    def parse(self, file_path: Path) -> list[RawTransaction]:
        try:
            with open_pdf(file_path, passwords=self._passwords) as pdf:
                all_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        except Exception as exc:
            raise ParseError(f"Failed to open Bancolombia savings PDF: {exc}") from exc

        period = _PERIOD_RE.search(all_text)
        if not period:
            raise ParseError(
                "Could not locate statement period (DESDE/HASTA) in savings PDF"
            )
        desde = date(int(period.group(1)), int(period.group(2)), int(period.group(3)))
        hasta = date(int(period.group(4)), int(period.group(5)), int(period.group(6)))

        account_match = _ACCOUNT_RE.search(all_text)
        account_number = account_match.group(1)[-4:] if account_match else None

        transactions: list[RawTransaction] = []

        for line in all_text.splitlines():
            row = _ROW_RE.match(line.strip())
            if not row:
                continue
            date_tok, description, amount_tok, _balance_tok = row.groups()
            day_s, month_s = date_tok.split("/")
            try:
                day, month = int(day_s), int(month_s)
            except ValueError:
                continue

            # Infer the year by picking whichever candidate (start-year or
            # end-year) places the row inside the statement period.
            tx_date: date | None = None
            for candidate_year in (desde.year, hasta.year):
                try:
                    candidate = date(candidate_year, month, day)
                except ValueError:
                    continue
                if desde <= candidate <= hasta:
                    tx_date = candidate
                    break
            if tx_date is None:
                continue

            try:
                amount = _parse_us_amount(amount_tok)
            except ValueError:
                continue

            if amount < 0:
                direction = TransactionDirection.DEBIT
                amount = -amount
            else:
                direction = TransactionDirection.CREDIT

            transactions.append(RawTransaction(
                date=tx_date,
                amount=amount,
                direction=direction,
                raw_description=description.strip(),
                bank_name=_BANK_NAME,
                source_file=str(file_path),
                position_in_statement=len(transactions),
                account_number=account_number,
            ))

        return transactions
