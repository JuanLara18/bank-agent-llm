# CLAUDE.md — Context for AI Agents

This file is the single source of truth for any AI agent (Claude Code, Cursor, etc.) working on this repository.
Read this file entirely before touching any code.

---

## Project Overview

**bank-agent-llm** is a local-first, privacy-focused financial intelligence pipeline.

It automatically:
1. Fetches bank statements (PDFs/Excel) from one or more email accounts via IMAP
2. Detects which bank each statement belongs to and parses it accordingly (Factory pattern)
3. Normalizes and stores all transactions in a local SQLite database
4. Uses a local LLM via **Ollama** to categorize raw transaction descriptions
5. Exposes the database for **Power BI** dashboards
6. Allows natural-language querying of the data via **Chat-to-SQL** (Ollama + local DB)

**Key principle:** All processing is 100% local. No financial data ever leaves the user's machine.

---

## Architecture

```
bank-agent-llm/
├── src/
│   ├── ingestion/       # Email connection, attachment download, deduplication
│   ├── parsers/         # Factory pattern: one parser class per bank
│   ├── enrichment/      # Ollama integration for transaction categorization
│   ├── storage/         # Database models, migrations, repository layer
│   └── chat/            # Chat-to-SQL interface using Ollama
├── config/
│   └── config.example.yaml   # Template (never commit the real config.yaml)
├── data/                # gitignored — raw attachments and processed outputs
│   ├── raw/
│   └── processed/
├── tests/               # Mirrors src/ structure
├── docs/                # Architecture decisions, setup guides, roadmap
├── scripts/             # One-off or utility scripts
└── .github/             # Issue templates, PR template
```

### Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `ingestion` | IMAP connection to multiple email accounts, download new attachments, track already-processed emails (never re-process) |
| `parsers` | Abstract `BankParser` base class + concrete implementations per bank. A `ParserFactory` receives a file and returns the right parser. |
| `enrichment` | Sends raw transaction descriptions to a local Ollama model for category classification. Handles batching and caching. |
| `storage` | SQLAlchemy models, Alembic migrations. Single repository class per entity. No raw SQL outside this module. |
| `chat` | LangChain or direct Ollama API for Text-to-SQL. Reads schema, generates SQL, executes, returns natural language answer. |

---

## Technology Stack

- **Language:** Python 3.11+
- **Package manager:** `uv` (fast, modern — preferred over pip)
- **Database:** SQLite (default) — can be swapped for PostgreSQL via config
- **ORM:** SQLAlchemy 2.x + Alembic for migrations
- **AI/LLM:** Ollama (local) — default models: `llama3.2` for categorization, `phi3` for chat
- **PDF parsing:** `pdfplumber` (primary), `PyPDF2` (fallback)
- **Email:** `imaplib` + `email` stdlib, wrapped in a clean IMAP client
- **Config:** Pydantic Settings v2 — reads from `config/config.yaml` + `.env`
- **Testing:** `pytest` + `pytest-cov`
- **Linting:** `ruff` (linter + formatter)
- **Type checking:** `mypy`

---

## Design Patterns & Conventions

### Factory Pattern for Parsers
Every bank has its own parser class in `src/parsers/`. Adding support for a new bank means:
1. Create `src/parsers/my_bank.py` with a class extending `BankParser`
2. Register it in `src/parsers/factory.py`
3. Add its detection logic (by email sender or PDF text signature)
4. Write tests in `tests/parsers/test_my_bank.py`

Never modify existing parsers to add a new bank — always add a new file.

### Configuration
All user-specific settings live in `config/config.yaml` (gitignored).
`config/config.example.yaml` is the documented template committed to the repo.
Code reads config via `src/config.py` using Pydantic Settings — never read env vars or files directly in business logic.

### Database
- All DB access goes through the repository layer in `src/storage/`
- Migrations are managed with Alembic — never alter the schema manually
- Transaction deduplication is handled by a unique constraint on `(bank_id, date, amount, description_hash)`

### Testing
- Unit tests mock external dependencies (IMAP, Ollama HTTP calls)
- At least one integration test per parser using a real (anonymized) sample PDF in `tests/fixtures/`
- Run tests: `pytest`
- Coverage target: 80%+

---

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Always deployable. Protected. Only merges from `develop` via PR. |
| `develop` | Integration branch. Feature branches merge here first. |
| `feature/<name>` | New functionality (e.g., `feature/bancolombia-parser`) |
| `fix/<name>` | Bug fixes (e.g., `fix/imap-reconnect`) |
| `docs/<name>` | Documentation only (e.g., `docs/setup-guide`) |
| `chore/<name>` | Tooling, deps, config (e.g., `chore/add-ruff`) |

**PR rules:**
- Every PR must reference a GitHub Issue
- PR title format: `feat: add Bancolombia parser (#12)`
- Squash merge into `develop`, merge commit into `main`
- No force-push to `main` or `develop`

---

## Commit Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add IMAP attachment downloader
fix: handle empty PDF pages in parser
docs: add architecture diagram
chore: add ruff linting config
test: add unit tests for ParserFactory
refactor: extract deduplication logic to storage module
```

---

## What NOT to Do

- Do NOT commit `config/config.yaml`, `.env`, or any file with credentials
- Do NOT put business logic in `scripts/` — it belongs in `src/`
- Do NOT skip migrations — always use Alembic to change the schema
- Do NOT call Ollama directly from parsers or ingestion — only through `enrichment/`
- Do NOT add a new bank by modifying an existing parser file
- Do NOT use `print()` for logging — use the `logging` stdlib module
- Do NOT store raw PDFs in git — they go in `data/raw/` (gitignored)

---

## Development Phases (Roadmap)

Track progress in GitHub Issues with the milestones below.

| Milestone | Description |
|-----------|-------------|
| **M1: Foundation** | Repo setup, CI, config system, DB schema, base classes |
| **M2: Ingestion** | IMAP client, attachment download, deduplication |
| **M3: First Parser** | ParserFactory + first bank implementation |
| **M4: Enrichment** | Ollama categorization pipeline |
| **M5: Visualization** | Power BI connection guide + sample dashboard |
| **M6: Chat** | Chat-to-SQL local interface |
| **M7: Portability** | Docker, one-command setup, full user documentation |

---

## Running Locally

```bash
# 1. Clone and enter
git clone https://github.com/<user>/bank-agent-llm.git
cd bank-agent-llm

# 2. Install uv (if not installed)
pip install uv

# 3. Create environment and install deps
uv sync

# 4. Copy config template and fill in your data
cp config/config.example.yaml config/config.yaml

# 5. Run DB migrations
uv run alembic upgrade head

# 6. Run the pipeline
uv run python -m bank_agent_llm.main
```

---

## Key Files to Know

| File | Purpose |
|------|---------|
| `src/config.py` | Pydantic Settings — single entry point for all config |
| `src/parsers/base.py` | Abstract `BankParser` class — all parsers extend this |
| `src/parsers/factory.py` | `ParserFactory` — maps files to their parser class |
| `src/storage/models.py` | SQLAlchemy models |
| `src/storage/migrations/` | Alembic migration files |
| `config/config.example.yaml` | Documented config template |

---

*This file should be updated whenever a new module is added, a design decision is made, or the architecture changes.*
