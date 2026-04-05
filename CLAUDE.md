# CLAUDE.md

Read this file before touching any code. For architecture diagrams and the data model see `docs/architecture.md`.

---

## What this project does

**bank-agent-llm** is a local-first Python library and CLI tool that:
1. Imports bank statement files (PDF/XLSX) from a local path or IMAP email accounts
2. Detects the bank and parses each statement with the correct parser (Factory pattern)
3. Stores all transactions in a single SQLite/PostgreSQL database
4. Categorizes transaction descriptions using a local LLM via Ollama (optional — rules engine runs first)
5. Exposes data via a terminal dashboard, Power BI, and a natural-language CLI chat interface

All processing is local. No financial data reaches any external API.

---

## Module responsibilities

| Module | Responsibility |
|--------|---------------|
| `pipeline.py` | Public library API — orchestrates all stages. CLI delegates here. |
| `cli.py` | Typer CLI — argument parsing, output formatting, exit codes only. No business logic. |
| `ingestion/` | IMAP client, attachment download, deduplication via `processed_emails` table |
| `parsers/` | `BankParser` base, `ParserFactory` (hint optimization), one file per bank |
| `enrichment/` | Rules engine (fast) → Ollama fallback (optional). Category cache. |
| `storage/` | SQLAlchemy models, Alembic migrations, repository classes |
| `chat/` | Read-only Text-to-SQL via Ollama — schema injection, query preview, execution |

---

## Technology stack

| Concern | Library |
|---------|---------|
| CLI | `typer` + `rich` |
| Config | `pydantic-settings` v2 + custom YAML loader (see Configuration section) |
| Email | `imapclient` |
| PDF | `pdfplumber` |
| Spreadsheet | `openpyxl` |
| ORM | `sqlalchemy` 2.x |
| Migrations | `alembic` |
| LLM | `httpx` → Ollama REST API |
| Resilience | `tenacity` |
| Packaging | `uv` + `hatchling` |
| Testing | `pytest` + `pytest-httpx` |
| Linting | `ruff` |
| Types | `mypy` strict |

---

## CLI commands

```
bank-agent run              Full pipeline: fetch → parse → enrich → store
bank-agent import <path>    Import statement files from a local path (primary method)
bank-agent fetch            Download new statements from email accounts
bank-agent parse            Parse downloaded files in data/raw/
bank-agent enrich           Categorise transactions via Ollama
bank-agent status           Terminal dashboard summary
bank-agent chat             Natural-language query session (read-only)
bank-agent config-check     Validate configuration file
bank-agent db migrate       Apply pending Alembic migrations
bank-agent db purge         Delete transactions before a given date
bank-agent db reset         Drop and recreate the database
bank-agent --version        Print version
```

---

## Adding a new bank parser

1. Create `src/bank_agent_llm/parsers/<bank_slug>.py` extending `BankParser`
2. Implement `bank_name`, `can_parse(file_path, *, hint="")`, and `parse()`
3. Register in `src/bank_agent_llm/parsers/factory.py`
4. Add anonymized sample PDF to `tests/fixtures/`
5. Write tests in `tests/parsers/test_<bank_slug>.py`

Full guide: `docs/adding-a-parser.md`

---

## Configuration

Config lives in `config/config.yaml` (gitignored). Template: `config/config.example.yaml`.

`config.yaml` uses `${ENV_VAR}` tokens for secrets. **pydantic-settings does not expand these natively from YAML** — the config loader in `src/bank_agent_llm/config.py` applies `os.path.expandvars` to the raw YAML string before parsing. Actual secret values belong in `.env`, which is also gitignored.

---

## Database

- All DB access via the repository layer (`src/storage/`)
- Schema changes via Alembic only
- Unique constraint on transactions: `(account_id, date, amount, description_hash, position_in_statement)`
- Chat interface always uses a **read-only** SQLAlchemy connection — never write access from chat

---

## Branch and commit conventions

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases only — merge from `develop` at milestone close |
| `develop` | Integration branch |
| `feature/<name>` | New functionality |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Documentation only |
| `chore/<name>` | Tooling, deps, config |
| `refactor/<name>` | Behaviour-neutral code changes |

Commit format: `type: short description` — types: `feat fix docs chore test refactor`

---

## What NOT to do

- Do not commit `config/config.yaml`, `.env`, or any file with credentials
- Do not put business logic in `cli.py` — it belongs in `pipeline.py` or a module
- Do not call Ollama directly outside `src/enrichment/` and `src/chat/`
- Do not skip the rules engine — LLM enrichment is a fallback, not the first step
- Do not modify an existing parser to add a new bank — always add a new file
- Do not bypass Alembic to change the schema
- Do not allow write SQL from the chat interface — always use a read-only connection
- Do not use `print()` — use `logging` in library code, `rich` in CLI code
- Do not store PDFs in git — they belong in `data/raw/` (gitignored)

---

*Update this file when a module is added, a dependency changes, or an architectural decision is made.*
