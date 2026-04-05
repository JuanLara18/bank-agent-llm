"""Bancolombia credit card statement parser.

Supports password-protected PDFs from Bancolombia (NIT: 890.903.938-8).
Detects Visa and Mastercard credit card statements.

Row format (word-level extraction grouped by y-position):
    [auth_code?] DD/MM/YYYY  description...  $  amount  [N/M]  $  ...
    auth_code is a 6-character alphanumeric code (e.g. C07817, R02013, 023785).

Payments appear as negative amounts (e.g. ABONO WOMPI/PSE → -2.085.486,00).

Card number encoding: Bancolombia PDFs triple-encode styled text.
  "***************************111333333222" → un-triple → "***1332"
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

_BANK_NAME = "Bancolombia"
_SIGNATURE = "890.903.938-8"

# Auth codes are 6 alphanumeric characters (all caps or digits)
_AUTH_RE = re.compile(r"^[A-Z0-9]{6}$")

# Amount token: digits with optional periods/commas, optionally negative
_AMOUNT_RE = re.compile(r"^-?[\d.,]+$")

# Triple-encoded card tail: groups of 3 identical digits at end of token
# e.g. "***111333333222" → captures "111333333222" → un-triple → "1332"
_TRIPLE_DIGITS_RE = re.compile(r"(\d{3,})$")


def _untriple(encoded: str) -> str:
    """Un-triple a sequence of digits encoded in Bancolombia's triple-char style.

    "111333333222" (groups: 111, 333, 333, 222) → "1332"
    Only works when len(encoded) is divisible by 3 and each group is uniform.
    Returns empty string if decoding fails.
    """
    if len(encoded) % 3 != 0:
        return ""
    result = []
    for i in range(0, len(encoded), 3):
        chunk = encoded[i : i + 3]
        if chunk[0] == chunk[1] == chunk[2]:
            result.append(chunk[0])
        else:
            return ""  # not triple-encoded
    return "".join(result)


def _extract_card_digits(tokens: list[str]) -> str | None:
    """Try to extract the last 4 card digits from a row of Bancolombia tokens.

    Looks for the triple-encoded card number pattern (e.g. "***111333333222").
    Returns the last 4 actual digits, or None.
    """
    for token in tokens:
        m = _TRIPLE_DIGITS_RE.search(token)
        if m:
            decoded = _untriple(m.group(1))
            if len(decoded) >= 4:
                return decoded[-4:]
    return None


class BancolombiaParser(BankParser):
    """Parser for Bancolombia credit card PDF statements."""

    def __init__(self, passwords: list[str] | None = None) -> None:
        self._passwords = passwords or []

    @property
    def bank_name(self) -> str:
        return _BANK_NAME

    def can_parse(self, file_path: Path, *, hint: str = "") -> bool:
        if file_path.suffix.lower() != ".pdf":
            return False
        return _SIGNATURE in hint

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

                        # Extract card number from triple-encoded header rows
                        if account_number is None:
                            candidate = _extract_card_digits(tokens)
                            if candidate:
                                account_number = candidate

                        tx = _parse_row(tokens, str(file_path), len(transactions))
                        if tx is not None:
                            tx.account_number = account_number
                            transactions.append(tx)

        except Exception as exc:
            raise ParseError(f"Failed to parse Bancolombia PDF: {exc}") from exc

        return transactions


def _parse_row(
    tokens: list[str],
    source_file: str,
    position: int,
) -> RawTransaction | None:
    """Try to parse a single row of tokens as a Bancolombia transaction.

    Returns None if the row does not look like a transaction.
    """
    if len(tokens) < 4:
        return None

    idx = 0
    # Optional auth code (6-char alphanumeric) before date
    if _AUTH_RE.match(tokens[0]):
        idx = 1

    if idx >= len(tokens) or not is_date(tokens[idx]):
        return None

    tx_date = parse_date(tokens[idx])
    idx += 1

    # Find the "$" separator between description and amount
    dollar_idx = None
    for i in range(idx, len(tokens)):
        if tokens[i] == "$":
            dollar_idx = i
            break

    if dollar_idx is None or dollar_idx <= idx:
        return None

    description = " ".join(tokens[idx:dollar_idx]).strip()
    if not description:
        return None

    # Amount is immediately after "$"
    amount_idx = dollar_idx + 1
    if amount_idx >= len(tokens):
        return None

    raw_amount_str = tokens[amount_idx]
    if not _AMOUNT_RE.match(raw_amount_str):
        return None

    try:
        amount = parse_cop(raw_amount_str)
    except ValueError:
        return None

    # Negative amounts are credits (payments/refunds); positive are debits (purchases)
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
