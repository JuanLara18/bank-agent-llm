# CLAUDE.md

Read this file before touching any code. For architecture and data model see `docs/architecture.md`. For milestone status see `docs/roadmap.md`.

---

## What this project does

**bank-agent-llm** is a local-first Python library and CLI tool that:
1. Downloads bank statement PDFs from Gmail (OAuth2) and Outlook (IMAP)
2. Also imports files from a local path — primary method for initial load
3. Detects the bank and parses each statement with the correct parser (Factory pattern)
4. Stores all transactions in a SQLite database (PostgreSQL-ready)
5. Categorizes transactions using a keyword rules engine (99%+ coverage) with Ollama as optional fallback
6. Displays a Rich terminal dashboard with spending by category, merchant, month, and day of week
7. Exposes data via a future web dashboard (Streamlit, M7) and natural-language chat (Ollama, M8)

All processing is local. No financial data reaches any external API.

---

## Current state (as of 2026-04-12, v0.1.1)

| Milestone | Status | Key deliverable |
|-----------|--------|-----------------|
| M1 Foundation | ✅ Done | CLI skeleton, DB, config |
| M2 File Import | ✅ Done | `bank-agent import <path>` |
| M3 First Parsers | ✅ Done | Bancolombia (tarjeta + ahorros), Falabella CMR, Scotiabank/DaviBank |
| M4 Enrichment | ✅ Done | Rules engine 99.3% coverage, Ollama fallback |
| M5 Email Ingestion | ✅ Done | Gmail OAuth2 + Outlook IMAP |
| M6 Status Dashboard | ✅ Done | `bank-agent status` Rich terminal report |
| M7 Web Dashboard | ✅ Done | Streamlit `bank-agent dashboard` |
| M8 Chat | 🔜 Next | `bank-agent chat` (requires Ollama) |
| M9 Portability | 🔜 | Docker, Makefile, docs |

**Real data:** 1637 unique transactions (Jan 2025–Mar 2026) after v0.1.1 dedup cleanup. 807 tagged by rules (49%), 131 tagged by Ollama (8%), 699 pending re-enrichment after latest import.

**Known import gaps** (tracked in `docs/known-gaps.md`):
- 14 old-format Bancolombia card statements (VISA_2158/MASTERCARD_0542, Feb–Aug 2025) — layout predates the current `_parse_row` grammar. Low priority; not blocking any milestone.

---

## Module responsibilities

| Module | Responsibility |
|--------|---------------|
| `pipeline.py` | Public library API — orchestrates all stages. CLI delegates here. |
| `cli.py` | Typer CLI — argument parsing, output formatting, exit codes only. No business logic. |
| `ingestion/gmail_client.py` | Gmail API OAuth2 — downloads PDFs from Gmail accounts |
| `ingestion/imap_client.py` | Generic IMAP — downloads PDFs from Outlook and other accounts |
| `ingestion/file_scanner.py` | Recursively finds `.pdf`/`.xlsx` in a directory |
| `ingestion/dedup.py` | SHA-256 file hash deduplication |
| `parsers/` | `BankParser` base, `ParserFactory`, one file per bank |
| `enrichment/tags.py` | `TagTaxonomy` — two-level tag hierarchy with expense flags |
| `enrichment/rules.py` | `SignatureRules` — keyword + direction matching engine |
| `enrichment/ollama.py` | Ollama batch client (15 tx/call), structured JSON, retries |
| `enrichment/enricher.py` | Orchestrates: rules → merchant cache → LLM |
| `storage/models.py` | SQLAlchemy models |
| `storage/repository.py` | Repository classes per model + `StatsRepository` for analytics |
| `storage/migrations/` | Alembic migrations (001 initial, 002 enrichment fields) |
| `dashboard/app.py` | Streamlit web dashboard with Plotly charts |
| `chat/` | (M8) Read-only Text-to-SQL via Ollama |

---

## Technology stack

| Concern | Library |
|---------|---------|
| CLI | `typer` + `rich` |
| Config | `pydantic-settings` v2 + custom YAML loader |
| Env vars | `python-dotenv` — loaded automatically at CLI startup |
| Gmail | `google-api-python-client` + `google-auth-oauthlib` |
| IMAP | `imapclient` |
| PDF | `pdfplumber` |
| Spreadsheet | `openpyxl` |
| ORM | `sqlalchemy` 2.x |
| Migrations | `alembic` |
| LLM | `httpx` → Ollama REST API |
| Resilience | `tenacity` |
| Web dashboard | `streamlit` + `plotly` |
| Packaging | `hatchling` |
| Testing | `pytest` + `pytest-httpx` |
| Linting | `ruff` |
| Types | `mypy` strict |

---

## Daily workflow

```bash
# Get new statements from email
bank-agent fetch

# Import any new PDFs in data/raw/ (also run after manual downloads)
bank-agent import data/raw

# Tag new transactions
bank-agent enrich

# See the terminal dashboard
bank-agent status

# Open the web dashboard in a browser
bank-agent dashboard
```

---

## Setup requirements

**Files needed (all gitignored):**

| File | Purpose |
|------|---------|
| `config/config.yaml` | Main config (copy from `config.example.yaml`) |
| `config/gmail_credentials.json` | OAuth2 client secrets from Google Cloud Console |
| `config/gmail_token.json` | Auto-generated after first `bank-agent fetch` |
| `.env` | Secrets: `PDF_PASSWORD_1`, `PDF_PASSWORD_2`, `EMAIL_OUTLOOK_PASS` |

**First-time setup:**
```bash
bank-agent db migrate          # create/update schema
bank-agent fetch               # authorize Gmail in browser (first run only)
bank-agent import data/raw     # import any existing PDFs
bank-agent enrich              # categorize
bank-agent status              # view dashboard
```

---

## Adding a new bank parser

1. Create `src/bank_agent_llm/parsers/<bank_slug>.py` extending `BankParser`
2. Implement `bank_name`, `can_parse(file_path, *, hint="")`, and `parse()`
3. Register in `src/bank_agent_llm/parsers/factory.py`
4. Add anonymized sample PDF to `tests/fixtures/`
5. Write tests in `tests/parsers/test_<bank_slug>.py`

---

## Enrichment rules

- Bundled rules: `src/enrichment/data/rules.yaml` — edit to add merchants
- User overrides: `config/categories.yaml` — loaded first, higher priority
- Tag taxonomy: `src/enrichment/data/tags.yaml` — add new tags here

---

## Configuration

`config/config.yaml` uses `${ENV_VAR}` tokens for secrets. The loader applies `os.path.expandvars` before parsing. Secrets live in `.env`.

PDF passwords: Colombian banks encrypt PDFs with the account holder's cédula. Set as `PDF_PASSWORD_1`, `PDF_PASSWORD_2` in `.env`.

Gmail: institutional Google Workspace accounts (`@unal.edu.co`) require OAuth2. Put `gmail_credentials.json` in `config/` and run `bank-agent fetch` once to authorize.

---

## Database

- All DB access via the repository layer (`src/storage/repository.py`)
- Schema changes via Alembic only — never modify tables directly
- Unique constraint on transactions: `(account_id, date, amount, description_hash, position_in_statement)`
- **Transaction dedup is two-phase** (v0.1.1): cross-file dedup by `(account_id, date, amount, description_hash)` ignoring position, then same-file dedup including `position_in_statement`. This handles credit card statements that carry forward prior-month transactions.
- **Spending metrics** exclude tags with `is_expense: false` (`pago-tarjeta`, `transferencia`, `cancelada`, `ingreso`). The `build_report()` and dashboard filter these as internal transfers.
- `tag_source` values: `pending | keyword_rule | direction_rule | llm | llm_cache | manual`
- Chat interface (M8) must use a **read-only** SQLAlchemy connection
- **Merchant normalization**: keyword rules catch common patterns deterministically; `build_report()` and dashboard normalize casing so LLM variants group together.
- Migrations: 001 initial, 002 enrichment fields, 003 pipeline runs, 004 cross-file dedup cleanup, 005 remove empty accounts, 006 reset fragmented merchants

---

## Branch and commit conventions

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases only |
| `develop` | Integration branch — merge features here |
| `feature/<name>` | New functionality |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Documentation only |
| `chore/<name>` | Tooling, deps, config |
| `refactor/<name>` | Behaviour-neutral changes |

Commit format: `type: short description` — types: `feat fix docs chore test refactor`

**Git workflow:**
1. Always work on `develop` — create topic branches from it (`fix/thing`, `feat/thing`, etc.)
2. One logical change per branch, one commit per branch (squash if needed)
3. Merge to `develop` with `--no-ff` to preserve branch history
4. Delete topic branches after merge (local and remote)
5. For releases: merge `develop` → `main` with `--no-ff`, tag on `main`, then sync `develop` back
6. Simple commit messages — no `Co-Authored-By`, no emoji, just `type: description`
7. Verify each git step before proceeding — never batch destructive operations

---

## What NOT to do

- Do not commit `config/config.yaml`, `.env`, `config/gmail_credentials.json`, `config/gmail_token.json`, or any file with credentials
- Do not put business logic in `cli.py` — it belongs in `pipeline.py` or a module
- Do not call Ollama directly outside `src/enrichment/` and `src/chat/`
- Do not skip the rules engine — LLM enrichment is a fallback, not the first step
- Do not modify an existing parser to add a new bank — always add a new file
- Do not bypass Alembic to change the schema
- Do not allow write SQL from the chat interface — read-only connection always
- Do not use `print()` — `logging` in library code, `rich` in CLI code
- Do not store real PDFs in git — they belong in `data/raw/` (gitignored)

---

*Update this file when a module is added, a dependency changes, or an architectural decision is made.*
