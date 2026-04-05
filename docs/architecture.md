# Architecture

## Overview

bank-agent-llm is structured as a layered ETL pipeline with a local LLM layer on top.

```
┌─────────────────────────────────────────────────────────┐
│                    INGESTION LAYER                       │
│  IMAP Client → Filter Attachments → Deduplication       │
│  (src/ingestion/)                                        │
└─────────────────────────┬───────────────────────────────┘
                          │ raw PDF/XLS files
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    PARSER FACTORY                        │
│  Detect bank → Select Parser → Extract transactions      │
│  (src/parsers/)                                          │
└─────────────────────────┬───────────────────────────────┘
                          │ normalized Transaction objects
                          ▼
┌─────────────────────────────────────────────────────────┐
│                   ENRICHMENT LAYER                       │
│  Raw description → Ollama LLM → Category + confidence   │
│  (src/enrichment/)                                       │
└─────────────────────────┬───────────────────────────────┘
                          │ enriched Transaction objects
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    STORAGE LAYER                         │
│  SQLAlchemy models + Alembic migrations + SQLite DB      │
│  (src/storage/)                                          │
└──────────────┬──────────────────────┬───────────────────┘
               │                      │
               ▼                      ▼
┌──────────────────────┐   ┌─────────────────────────────┐
│  Power BI Dashboard  │   │   Chat-to-SQL Interface      │
│  (ODBC / SQLite)     │   │   Ollama → SQL → Answer      │
│                      │   │   (src/chat/)                │
└──────────────────────┘   └─────────────────────────────┘
```

## Data Model

### Core Tables

**accounts** — one row per bank account tracked
```
id, bank_name, account_number_hash, owner_email, currency, created_at
```

**transactions** — one row per transaction
```
id, account_id, date, amount, direction (debit/credit),
raw_description, normalized_description, category_id,
category_confidence, source_file, created_at
```
Unique constraint: `(account_id, date, amount, description_hash)` — prevents duplicates.

**categories** — user-defined or AI-suggested
```
id, name, parent_id, color
```

**processed_emails** — deduplication registry
```
id, email_account, message_id, subject, processed_at
```

## Parser Pattern

```python
# base class (src/parsers/base.py)
class BankParser(ABC):
    @abstractmethod
    def can_parse(self, file_path: Path) -> bool: ...

    @abstractmethod
    def parse(self, file_path: Path) -> list[Transaction]: ...

# factory (src/parsers/factory.py)
class ParserFactory:
    _parsers: list[BankParser] = [...]

    def get_parser(self, file_path: Path) -> BankParser:
        for parser in self._parsers:
            if parser.can_parse(file_path):
                return parser
        raise UnsupportedBankError(file_path)
```

## Configuration Schema

```yaml
# config/config.example.yaml

database:
  url: "sqlite:///data/bank_agent.db"  # or postgresql://...

email_accounts:
  - name: "personal"
    imap_host: "imap.gmail.com"
    imap_port: 993
    username: "your@gmail.com"
    password: "${EMAIL_PASSWORD}"  # reads from .env

ollama:
  base_url: "http://localhost:11434"
  categorization_model: "llama3.2"
  chat_model: "phi3"

categories:
  - name: "Food & Dining"
    subcategories: ["Restaurants", "Groceries", "Delivery"]
  - name: "Transport"
    subcategories: ["Fuel", "Rideshare", "Public Transit"]
  # ... more categories
```

## Technology Choices (ADRs)

### SQLite over PostgreSQL (default)
**Decision:** Use SQLite as the default database.
**Reason:** Zero-setup for new users. Power BI can connect directly via ODBC. Can be switched to PostgreSQL via a single config line.

### uv over pip/poetry
**Decision:** Use `uv` for dependency management.
**Reason:** Significantly faster installs, built-in virtual env management, compatible with `pyproject.toml`.

### pdfplumber over PyPDF2
**Decision:** Use `pdfplumber` as primary PDF library.
**Reason:** Better handling of tabular data in PDFs (essential for bank statements). PyPDF2 as fallback for simple text extraction.

### Ollama over OpenAI API
**Decision:** Use local Ollama models exclusively.
**Reason:** Bank data is sensitive. Users should never need to send financial information to external APIs.
