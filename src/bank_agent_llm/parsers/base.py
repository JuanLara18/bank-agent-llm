"""Abstract base class for all bank parsers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
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
    # Optional fields that some banks provide
    reference: str | None = None
    balance_after: Decimal | None = None


class BankParser(ABC):
    """Base class for all bank statement parsers.

    To add a new bank:
    1. Subclass this in src/parsers/<bank_slug>.py
    2. Implement can_parse() and parse()
    3. Register in src/parsers/factory.py
    See docs/adding-a-parser.md for the full guide.
    """

    @property
    @abstractmethod
    def bank_name(self) -> str:
        """Human-readable bank name (e.g. 'Bancolombia')."""

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Return True if this parser can handle the given file.

        Should be fast — typically just checks extension and a text signature
        on the first page without parsing the full document.
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
