# bank-agent-llm

> Local-first, AI-powered ETL pipeline for personal financial intelligence.

Automatically fetches bank statements from multiple email accounts, parses them across different bank formats, categorizes transactions using a local LLM (Ollama), and prepares a unified database for Power BI dashboards and natural-language Chat-to-SQL queries.

**100% local processing — your financial data never leaves your machine.**

---

## Features

- Connects to multiple email accounts via IMAP to fetch bank statement attachments
- Detects bank format automatically and routes to the correct parser (Factory pattern)
- Normalizes transactions from multiple banks into a single schema
- Uses **Ollama** (local LLM) to auto-categorize raw transaction descriptions
- Exports to a local SQLite database for **Power BI** dashboards
- Ask questions about your finances in natural language via a local Chat-to-SQL interface
- Incremental updates — only processes new statements on each run
- Portable: minimal configuration to set up for any user

---

## Architecture

```
Email Accounts (IMAP)
        │
        ▼
  [Ingestion Layer]
  Download attachments
  Track processed emails
        │
        ▼
  [Parser Factory]
  Detect bank → Route to parser
  Bancolombia / Nequi / Nubank / ...
        │
        ▼
  [Enrichment Layer]
  Ollama LLM → Categorize transactions
        │
        ▼
  [Storage Layer]
  SQLite DB (SQLAlchemy + Alembic)
        │
    ┌───┴────┐
    ▼        ▼
Power BI   Chat-to-SQL
Dashboard  (Ollama)
```

---

## Supported Banks

| Bank | Status |
|------|--------|
| *(first bank coming in M3)* | Planned |

Adding a new bank requires creating one parser file. See [CLAUDE.md](CLAUDE.md) and [docs/adding-a-parser.md](docs/adding-a-parser.md).

---

## Quick Start

> Detailed setup instructions: [docs/setup.md](docs/setup.md)

```bash
git clone https://github.com/JuanLara18/bank-agent-llm.git
cd bank-agent-llm
pip install uv
uv sync
cp config/config.example.yaml config/config.yaml
# Edit config.yaml with your email credentials and bank settings
uv run alembic upgrade head
uv run python -m bank_agent_llm.main
```

**Prerequisites:** Python 3.11+, [Ollama](https://ollama.ai) installed and running locally.

---

## Project Status

Currently in **M1: Foundation** phase. See [docs/roadmap.md](docs/roadmap.md) for the full plan.

---

## Contributing

This project follows a GitHub Flow adapted for solo/small-team development.
See [CONTRIBUTING.md](CONTRIBUTING.md) and [CLAUDE.md](CLAUDE.md) for conventions.

---

## Privacy

No data is sent to external APIs. All LLM inference runs locally via Ollama. Bank credentials are stored only in your local `config/config.yaml` (gitignored).

---

## License

MIT
