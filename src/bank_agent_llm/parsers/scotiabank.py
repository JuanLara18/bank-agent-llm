"""Scotiabank Colpatria credit card statement parser.

Supports unencrypted PDFs from Scotiabank Colpatria Colombia.

Signature: "scotiabankcolpatria.com" or "Puntos Cencosud" in first-page text.

The statement has two sections:
  - "Tus pagos y abonos" → CREDIT direction
  - "Transacciones del periodo" → DEBIT direction

Row format (word-level extraction):
    DD/MM/YYYY  comprobante(6digits)  description...  $  amount  N/M  $  capital  $  saldo  MV%  EA%

Amounts are integer COP values (no decimal separator used consistently).
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

_BANK_NAME = "Scotiabank Colpatria"
_SIGNATURES = ("scotiabankcolpatria.com", "Puntos Cencosud", "Colpatria")

# Section header keywords (lowercased for matching)
_SECTION_PAYMENTS = "pagos"       # "Tus pagos y abonos"
_SECTION_PURCHASES = "transacciones"  # "Transacciones del periodo"

# Comprobante: exactly 6 digits
_COMPROBANTE_RE = re.compile(r"^\d{6}$")

# Cuotas: N/M
_CUOTAS_RE = re.compile(r"^\d+/\d+$")

# Percentage token: e.g. "1,89%" or "25,25%"
_PERCENT_RE = re.compile(r"^\d+[,.]?\d*%$")

# Contract number in header: "Contrato No: 00010105000014301065"
# We use the last 4 digits as the account identifier (e.g. 1065)
_CONTRACT_RE = re.compile(r"\b(\d{10,})\b")


class ScotiabankParser(BankParser):
    """Parser for Scotiabank Colpatria credit card PDF statements."""

    @property
    def bank_name(self) -> str:
        return _BANK_NAME

    def can_parse(self, file_path: Path, *, hint: str = "") -> bool:
        if file_path.suffix.lower() != ".pdf":
            return False
        return any(sig.lower() in hint.lower() for sig in _SIGNATURES)

    def parse(self, file_path: Path) -> list[RawTransaction]:
        transactions: list[RawTransaction] = []
        account_number: str | None = None
        # Default direction — updated as we encounter section headers
        current_direction = TransactionDirection.DEBIT

        try:
            with open_pdf(file_path) as pdf:
                for page in pdf.pages:
                    words = page.extract_words(x_tolerance=3, y_tolerance=3)
                    rows = group_words_by_row(words, y_tolerance=3.0)

                    for row in rows:
                        tokens = row_tokens(row)
                        line = " ".join(tokens).lower()

                        # Detect section headers
                        if _SECTION_PAYMENTS in line:
                            current_direction = TransactionDirection.CREDIT
                            continue
                        if _SECTION_PURCHASES in line:
                            current_direction = TransactionDirection.DEBIT
                            continue

                        # Extract account identifier from contract number
                        # Header row: ['Contrato', 'No:', '00010105000014301065']
                        if account_number is None:
                            m = _CONTRACT_RE.search(" ".join(tokens))
                            if m:
                                account_number = m.group(1)[-4:]

                        tx = _parse_row(
                            tokens,
                            str(file_path),
                            len(transactions),
                            current_direction,
                        )
                        if tx is not None:
                            tx.account_number = account_number
                            transactions.append(tx)

        except Exception as exc:
            raise ParseError(f"Failed to parse Scotiabank PDF: {exc}") from exc

        return transactions


def _parse_row(
    tokens: list[str],
    source_file: str,
    position: int,
    direction: TransactionDirection,
) -> RawTransaction | None:
    """Try to parse a single row as a Scotiabank Colpatria transaction."""
    if len(tokens) < 4:
        return None

    if not is_date(tokens[0]):
        return None

    tx_date = parse_date(tokens[0])
    idx = 1

    # Optional comprobante (6-digit reference)
    reference: str | None = None
    if idx < len(tokens) and _COMPROBANTE_RE.match(tokens[idx]):
        reference = tokens[idx]
        idx += 1

    # Find the "$" separator between description and amount
    dollar_idx = None
    for i in range(idx, len(tokens)):
        if tokens[i] == "$":
            dollar_idx = i
            break

    if dollar_idx is None or dollar_idx <= idx:
        return None

    description_tokens = tokens[idx:dollar_idx]
    description = " ".join(description_tokens).strip()

    if not description:
        return None

    # Amount follows "$"
    amount_idx = dollar_idx + 1
    if amount_idx >= len(tokens):
        return None

    raw_amount = tokens[amount_idx]
    try:
        amount = parse_cop(raw_amount)
    except ValueError:
        return None

    if amount <= Decimal("0"):
        # Skip zero or anomalous rows
        return None

    return RawTransaction(
        date=tx_date,
        amount=amount,
        direction=direction,
        raw_description=description,
        bank_name=_BANK_NAME,
        source_file=source_file,
        position_in_statement=position,
        reference=reference,
    )
