# Adding a New Bank Parser

This guide explains how to add support for a new bank. It should take about 30-60 minutes once you have a sample statement.

## Step 1: Understand the statement format

Open a sample PDF (or XLS) from the bank. Note:
- How is the bank identified? (email sender, logo text, header text)
- What columns does the transaction table have?
- What date format is used?
- How are debits/credits distinguished?
- Are there multiple pages or sections?

## Step 2: Create the parser file

Create `src/bank_agent_llm/parsers/<bank_slug>.py`:

```python
from pathlib import Path

import pdfplumber

from bank_agent_llm.parsers.base import BankParser, RawTransaction, TransactionDirection


class MyBankParser(BankParser):
    """Parser for MyBank PDF statements."""

    # Text that uniquely identifies this bank's PDFs (first-page signature)
    SIGNATURE = "MYBANK S.A."

    @property
    def bank_name(self) -> str:
        return "MyBank"

    def can_parse(self, file_path: Path, *, hint: str = "") -> bool:
        """Return True if this file belongs to MyBank.

        Uses the pre-extracted hint text when available to avoid
        reopening the PDF (ParserFactory handles extraction).
        """
        if file_path.suffix.lower() != ".pdf":
            return False
        text = hint or self._first_page_text(file_path)
        return self.SIGNATURE in text.upper()

    def parse(self, file_path: Path) -> list[RawTransaction]:
        """Extract transactions from the PDF."""
        transactions = []
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                for table in tables:
                    for row_idx, row in enumerate(table):
                        tx = self._parse_row(
                            row,
                            source_file=str(file_path),
                            position=page_num * 1000 + row_idx,
                        )
                        if tx:
                            transactions.append(tx)
        return transactions

    def _first_page_text(self, file_path: Path) -> str:
        with pdfplumber.open(file_path) as pdf:
            return pdf.pages[0].extract_text() or "" if pdf.pages else ""

    def _parse_row(
        self, row: list[str | None], source_file: str, position: int
    ) -> RawTransaction | None:
        # Parse each row — return None for header or empty rows
        ...
```

## Step 3: Register in the factory

Open `src/bank_agent_llm/parsers/factory.py` and add your parser:

```python
from bank_agent_llm.parsers.my_bank import MyBankParser

_PARSERS: list[BankParser] = [
    ExistingBankParser(),
    MyBankParser(),   # add here
]
```

## Step 4: Write tests

Create `tests/parsers/test_my_bank.py`:

```python
from pathlib import Path

import pytest

from bank_agent_llm.parsers.my_bank import MyBankParser

FIXTURE = Path("tests/fixtures/my_bank_sample.pdf")


def test_can_parse_returns_true_for_mybank_pdf() -> None:
    assert MyBankParser().can_parse(FIXTURE)


def test_can_parse_uses_hint_without_opening_file() -> None:
    parser = MyBankParser()
    # hint contains the signature — file path is irrelevant
    assert parser.can_parse(Path("any.pdf"), hint="MYBANK S.A. ACCOUNT SUMMARY")


def test_parse_returns_expected_transactions() -> None:
    transactions = MyBankParser().parse(FIXTURE)
    assert len(transactions) > 0
    assert transactions[0].amount is not None
    assert transactions[0].date is not None
    assert transactions[0].position_in_statement >= 0
```

Add an **anonymized** sample PDF to `tests/fixtures/my_bank_sample.pdf`.
Anonymized means: real PDF structure, dummy amounts and personal data.

## Step 5: Run the tests

```bash
pytest tests/parsers/test_my_bank.py -v
```

## Step 6: Open a PR

- Branch: `feature/my-bank-parser`
- PR title: `feat: add MyBank parser (#<issue>)`
- PR target: `develop`
