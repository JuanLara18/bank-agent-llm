# Roadmap

## Milestone 1: Foundation (current)
> Goal: A runnable Python project with zero functionality but all the scaffolding in place.

- [x] Git repo + branch strategy
- [x] CLAUDE.md (AI agent context)
- [x] README, CONTRIBUTING
- [ ] `pyproject.toml` with all dependencies declared
- [ ] `src/` package structure with `__init__.py` files
- [ ] `src/config.py` — Pydantic Settings reading `config/config.yaml`
- [ ] `config/config.example.yaml` — documented template
- [ ] `src/storage/models.py` — SQLAlchemy models (Account, Transaction, Category)
- [ ] First Alembic migration
- [ ] `src/parsers/base.py` — abstract `BankParser` class
- [ ] `src/parsers/factory.py` — `ParserFactory` skeleton
- [ ] CI with GitHub Actions: lint + test on every PR
- [ ] Issue templates + PR template

## Milestone 2: Ingestion
> Goal: Connect to real email accounts and download statement attachments.

- [ ] IMAP client wrapper (supports multiple accounts)
- [ ] Attachment filter (PDFs, XLS from known bank senders)
- [ ] Processed-email registry (avoid re-downloading)
- [ ] Save attachments to `data/raw/`
- [ ] Unit tests with mocked IMAP

## Milestone 3: First Parser
> Goal: Parse one real bank's statement end-to-end.

- [ ] Choose first bank (based on available samples)
- [ ] Implement concrete parser extending `BankParser`
- [ ] Register in `ParserFactory` with detection logic
- [ ] Store parsed transactions in DB
- [ ] Integration test with anonymized sample PDF in `tests/fixtures/`

## Milestone 4: Enrichment (Ollama)
> Goal: Auto-categorize every transaction using a local LLM.

- [ ] Ollama HTTP client wrapper
- [ ] Category taxonomy (defined in config)
- [ ] Batch categorization with caching (don't re-categorize known descriptions)
- [ ] Confidence score stored per transaction
- [ ] Unit tests with mocked Ollama responses

## Milestone 5: Visualization (Power BI)
> Goal: A working Power BI dashboard connected to the local DB.

- [ ] Power BI connection guide (ODBC or direct SQLite)
- [ ] Sample `.pbix` file with key reports:
  - Monthly spending by category
  - Income vs expenses timeline
  - Per-bank breakdown
  - Top merchants

## Milestone 6: Chat Interface
> Goal: Ask questions in natural language about your transactions.

- [ ] Text-to-SQL pipeline using Ollama
- [ ] Schema-aware prompting (inject DB schema into system prompt)
- [ ] Simple CLI chat loop
- [ ] Handle follow-up questions with conversation history

## Milestone 7: Portability
> Goal: Anyone can clone and run this in under 10 minutes.

- [ ] `docker-compose.yml` (app + Ollama)
- [ ] `make setup` or `./setup.sh` one-command bootstrap
- [ ] Full `docs/setup.md` walkthrough
- [ ] `docs/adding-a-parser.md` guide for contributors
- [ ] Config validation with friendly error messages
