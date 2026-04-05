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

Create `src/parsers/<bank_slug>.py`:

```python
from pathlib import Path
from src.parsers.base import BankParser
from src.storage.models import Transaction
import pdfplumber


class MyBankParser(BankParser):
    """Parser for MyBank PDF statements."""

    BANK_NAME = "MyBank"
    # Text that uniquely identifies this bank's PDFs
    SIGNATURE = "MYBANK S.A."

    def can_parse(self, file_path: Path) -> bool:
        """Return True if this file belongs to MyBank."""
        if file_path.suffix.lower() != ".pdf":
            return False
        with pdfplumber.open(file_path) as pdf:
            first_page_text = pdf.pages[0].extract_text() or ""
            return self.SIGNATURE in first_page_text.upper()

    def parse(self, file_path: Path) -> list[Transaction]:
        """Extract transactions from the PDF."""
        transactions = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                # Extract the transaction table
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        tx = self._parse_row(row)
                        if tx:
                            transactions.append(tx)
        return transactions

    def _parse_row(self, row: list) -> Transaction | None:
        # Parse each row into a Transaction object
        # Return None for header rows or empty rows
        ...
```

## Step 3: Register in the factory

Open `src/parsers/factory.py` and add your parser to the list:

```python
from src.parsers.my_bank import MyBankParser

_PARSERS = [
    ExistingBankParser(),
    MyBankParser(),   # add here
]
```

## Step 4: Write tests

Create `tests/parsers/test_my_bank.py`:

```python
from pathlib import Path
from src.parsers.my_bank import MyBankParser

FIXTURE_PATH = Path("tests/fixtures/my_bank_sample.pdf")

def test_can_parse_returns_true_for_mybank_pdf():
    parser = MyBankParser()
    assert parser.can_parse(FIXTURE_PATH)

def test_parse_returns_expected_transactions():
    parser = MyBankParser()
    transactions = parser.parse(FIXTURE_PATH)
    assert len(transactions) > 0
    assert transactions[0].amount is not None
    assert transactions[0].date is not None
```

Add an **anonymized** sample PDF to `tests/fixtures/my_bank_sample.pdf`.
Anonymized means: real structure, dummy amounts and names.

## Step 5: Run the test suite

```bash
pytest tests/parsers/test_my_bank.py -v
```

## Step 6: Open a PR

- Branch: `feature/my-bank-parser`
- PR title: `feat: add MyBank statement parser (#<issue>)`
- PR into `develop`
