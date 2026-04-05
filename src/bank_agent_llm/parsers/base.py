"""Abstract base class for all bank parsers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from enum import StrEnum
from pathlib import Path


class TransactionDirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


@dataclass
class RawTransaction:
    """A parsed transaction before enrichment (categorization)."""

    date: date
    amount: Decimal
    direction: TransactionDirection
    raw_description: str
    bank_name: str
    source_file: str
    currency: str = "COP"
    # Position within the statement — used as a dedup discriminator when
    # amount + date + description are identical (e.g. two coffees same day)
    position_in_statement: int = 0
    # Optional fields that some banks provide
    transaction_time: time | None = None
    reference: str | None = None
    balance_after: Decimal | None = None


class BankParser(ABC):
    """Base class for all bank statement parsers.

    To add a new bank:
    1. Subclass this in src/bank_agent_llm/parsers/<bank_slug>.py
    2. Implement bank_name, can_parse(), and parse()
    3. Register in src/bank_agent_llm/parsers/factory.py
    See docs/adding-a-parser.md for the full guide.
    """

    @property
    @abstractmethod
    def bank_name(self) -> str:
        """Human-readable bank name (e.g. 'Bancolombia')."""

    @abstractmethod
    def can_parse(self, file_path: Path, *, hint: str = "") -> bool:
        """Return True if this parser can handle the given file.

        Args:
            file_path: Path to the statement file.
            hint: Pre-extracted first-page text supplied by ParserFactory
                  to avoid redundant file opens. If empty, the parser may
                  extract it internally.

        Should be fast — only checks file extension and a text signature.
        """

    @abstractmethod
    def parse(self, file_path: Path) -> list[RawTransaction]:
        """Extract all transactions from the statement file.

        Args:
            file_path: Path to the downloaded statement (PDF or XLS).

        Returns:
            List of RawTransaction objects. Empty list if no transactions found.

        Raises:
            ParseError: If the file is corrupted or the format changed unexpectedly.
        """


class ParseError(Exception):
    """Raised when a parser cannot extract transactions from a file."""
