"""Falabella CMR credit card statement parser.

Supports password-protected PDFs from Banco Falabella Colombia.

Signature: "Tarjeta de Crédito CMR" or "Banco Falabella" in first-page text.

PDF encoding quirk: styled header text has each character doubled
  (TTaarrjjeettaa → Tarjeta) but transaction data rows are normal.

Row format (word-level extraction):
    DD/MM/YYYY  description...  TT  $amount  N  de  M  rate%  $cuota  $saldo

Payments appear with doubled minus sign in the amount field:
    --$944.714,94 → -944714.94 → CREDIT direction
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from bank_agent_llm.parsers.base import BankParser, ParseError, RawTransaction, TransactionDirection
from bank_agent_llm.parsers._utils import (
    group_words_by_row,
    is_date,
    open_pdf,
    parse_cop,
    parse_date,
    row_tokens,
)

_BANK_NAME = "Falabella CMR"

# Signatures that may appear in raw (possibly doubled) first-page text
_SIGNATURES = ("Tarjeta de Crédito CMR", "Banco Falabella", "BANCO FALABELLA", "CMR")

# Card number pattern in header (e.g. "4213 **** **** 1234" or "BFCO...")
_CARD_RE = re.compile(r"\b(\d{4}[\s*]+\d{4}[\s*]+\d{4}[\s*]+\d{4})\b")
_BFCO_RE = re.compile(r"BFCO(\d+)", re.IGNORECASE)

# "TT" token separates description from amount section (doubled "T" = transaction type)
_TT_TOKEN = "TT"

# Amount token pattern (may start with -- or $ or both)
_AMOUNT_RE = re.compile(r"^-{0,2}\$?-?[\d.,]+$")


class FalabellaParser(BankParser):
    """Parser for Falabella CMR credit card PDF statements."""

    def __init__(self, passwords: list[str] | None = None) -> None:
        self._passwords = passwords or []

    @property
    def bank_name(self) -> str:
        return _BANK_NAME

    def can_parse(self, file_path: Path, *, hint: str = "") -> bool:
        if file_path.suffix.lower() != ".pdf":
            return False
        return any(sig in hint for sig in _SIGNATURES)

    def parse(self, file_path: Path) -> list[RawTransaction]:
        transactions: list[RawTransaction] = []
        account_number: str | None = None

        try:
            with open_pdf(file_path, passwords=self._passwords) as pdf:
                for page in pdf.pages:
                    words = page.extract_words(x_tolerance=3, y_tolerance=3)
                    rows = group_words_by_row(words, y_tolerance=3.0)

                    for row in rows:
                        tokens = row_tokens(row)
                        line = " ".join(tokens)

                        # Try to extract card number from header area
                        if account_number is None:
                            m = _CARD_RE.search(line)
                            if m:
                                # Keep last 4 digits only
                                digits = re.sub(r"[^\d]", "", m.group(1))
                                account_number = digits[-4:]
                            else:
                                m2 = _BFCO_RE.search(line)
                                if m2:
                                    account_number = m2.group(1)[-4:]

                        tx = _parse_row(tokens, str(file_path), len(transactions))
                        if tx is not None:
                            tx.account_number = account_number
                            transactions.append(tx)

        except Exception as exc:
            raise ParseError(f"Failed to parse Falabella PDF: {exc}") from exc

        return transactions


def _parse_row(
    tokens: list[str],
    source_file: str,
    position: int,
) -> RawTransaction | None:
    """Try to parse a single row of tokens as a Falabella CMR transaction."""
    if len(tokens) < 4:
        return None

    if not is_date(tokens[0]):
        return None

    tx_date = parse_date(tokens[0])

    # Find "TT" separator (transaction type marker, comes from doubled "T")
    tt_idx = None
    for i in range(1, len(tokens)):
        if tokens[i] == _TT_TOKEN:
            tt_idx = i
            break

    if tt_idx is None:
        return None

    # Description is everything between date and "TT"
    description_tokens = tokens[1:tt_idx]
    # Falabella sometimes encodes description tokens with doubled chars — clean them
    description = " ".join(_maybe_dedouble(t) for t in description_tokens).strip()

    if not description:
        return None

    # Amount comes after "TT"
    amount_idx = tt_idx + 1
    if amount_idx >= len(tokens):
        return None

    raw_amount = tokens[amount_idx]
    if not _AMOUNT_RE.match(raw_amount):
        return None

    try:
        amount = parse_cop(raw_amount)
    except ValueError:
        return None

    # Negative = payment (credit); positive = purchase (debit)
    if amount < Decimal("0"):
        direction = TransactionDirection.CREDIT
        amount = abs(amount)
    else:
        direction = TransactionDirection.DEBIT

    return RawTransaction(
        date=tx_date,
        amount=amount,
        direction=direction,
        raw_description=description,
        bank_name=_BANK_NAME,
        source_file=source_file,
        position_in_statement=position,
    )


def _maybe_dedouble(text: str) -> str:
    """Dedouble only if the entire token is doubled-encoded."""
    if len(text) >= 2 and len(text) % 2 == 0:
        if all(text[i] == text[i + 1] for i in range(0, len(text), 2)):
            return text[::2]
    return text
