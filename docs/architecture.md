# Architecture

## Pipeline overview

```mermaid
flowchart LR
    A([Local Files\nor Email]) --> B[Ingestion]
    B --> C{Parser Factory}
    C --> D[Bank A]
    C --> E[Bank B]
    C --> F[Bank N]
    D & E & F --> G[Enrichment\nRules → Ollama]
    G --> H[(Database)]
    H --> I[Dashboard]
    H --> J[CLI Chat\nread-only]
```

## Layer detail

```mermaid
flowchart TD
    subgraph ing["Ingestion — src/ingestion/"]
        direction LR
        FS[Local Path\nbank-agent import] --> SCAN[File Scanner]
        IC[IMAP Client\nbank-agent fetch] --> AF[Attachment Filter]
        SCAN & AF --> DR[Dedup Registry]
        DR --> RAW[data/raw/]
    end

    subgraph par["Parsers — src/parsers/"]
        direction LR
        PF[ParserFactory\nextract hint once] --> BA[BankA]
        PF --> BB[BankB]
        PF --> BN[...]
    end

    subgraph enr["Enrichment — src/enrichment/"]
        direction LR
        RULES[Rules Engine\nkeyword/regex] --> CACHE[Cache]
        RULES -->|unmatched| OC[Ollama Client\noptional]
        OC --> CACHE
    end

    subgraph sto["Storage — src/storage/"]
        direction LR
        MOD[SQLAlchemy Models] --- REP[Repositories]
        MIG[Alembic Migrations] --> MOD
    end

    ing --> par
    par --> enr
    enr --> sto
```

## Data model

```mermaid
erDiagram
    accounts {
        int id PK
        string bank_name
        string account_number_hash
        string owner_email
        string currency
        datetime created_at
    }

    transactions {
        int id PK
        int account_id FK
        date date
        time transaction_time
        decimal amount
        string currency
        string direction
        string raw_description
        string normalized_description
        int category_id FK
        float category_confidence
        string source_file
        string description_hash
        int position_in_statement
        datetime created_at
    }

    categories {
        int id PK
        string name
        int parent_id FK
        string color
    }

    processed_emails {
        int id PK
        string email_account
        string message_id
        string subject
        datetime processed_at
    }

    file_processing_runs {
        int id PK
        string file_path
        string file_hash
        string status
        string bank_name
        int transaction_count
        string error_message
        datetime processed_at
    }

    pipeline_runs {
        int id PK
        string status
        string stages_completed
        int transactions_fetched
        int transactions_parsed
        int transactions_enriched
        datetime started_at
        datetime finished_at
    }

    accounts ||--o{ transactions : has
    categories ||--o{ transactions : classifies
    categories ||--o{ categories : parent
    file_processing_runs ||--o{ transactions : produced
```

**Deduplication:** unique constraint on `(account_id, date, amount, description_hash, position_in_statement)`. The `position_in_statement` discriminator handles identical transactions on the same day (e.g. two coffee purchases) where amount and description are the same.

## Parser pattern

```mermaid
classDiagram
    class BankParser {
        <<abstract>>
        +bank_name() str
        +can_parse(file_path, hint) bool
        +parse(file_path) list~RawTransaction~
    }

    class ParserFactory {
        -_parsers list~BankParser~
        +get_parser(file_path) BankParser
        +supported_banks() list~str~
        -_extract_pdf_hint(file_path) str
    }

    class BankAParser {
        +SIGNATURE = "..."
        +bank_name = "BankA"
        +can_parse(file_path, hint) bool
        +parse(file_path) list~RawTransaction~
    }

    BankParser <|-- BankAParser
    ParserFactory o-- BankParser
```

`ParserFactory` extracts the PDF first-page text **once per file** and passes it as `hint` to every `can_parse()` call. With N parsers and M files the cost is M PDF opens, not N×M.

## Categorization tiers

```mermaid
flowchart LR
    TX[Raw description] --> RE{Rules Engine\nkeyword match}
    RE -->|matched| CAT[Category assigned]
    RE -->|no match| OL[Ollama LLM\noptional]
    OL --> CAT
    CAT --> CACHE[Cache\nno re-processing]
```

Ollama is **optional**. If not available, transactions unmatched by the rules engine remain uncategorized and can be reviewed via `bank-agent status`. Rules are defined in `config.yaml` and cover the majority of repeat transactions (same 20 merchants = 80% of spend).

## Chat — read-only safety

```mermaid
sequenceDiagram
    participant U as User
    participant CLI as bank-agent chat
    participant LLM as Ollama
    participant DB as Database (read-only)

    U->>CLI: natural language question
    CLI->>LLM: schema + question → generate SQL
    LLM-->>CLI: SQL query
    CLI->>U: preview SQL (confirm)
    U->>CLI: confirm
    CLI->>DB: execute (read-only connection)
    DB-->>CLI: result rows
    CLI->>U: formatted answer
```

The chat interface always connects with a read-only SQLAlchemy URL. LLM-generated SQL is shown to the user before execution.

## Architectural decisions

### SQLite as default database
Zero setup. Power BI connects via ODBC. Switchable to PostgreSQL with one config line.

### Direct Ollama API over LangChain
Fewer dependencies, full prompt control, no framework abstractions between the LLM call and the code.

### imapclient over stdlib imaplib
Cleaner API with proper connection management. `imaplib` is verbose and error-prone for multi-folder, multi-account setups.

### tenacity for retries
Both IMAP and Ollama are network operations prone to transient failure. `tenacity` handles exponential backoff with one decorator.

### pdfplumber as primary PDF library
Handles multi-column tabular layouts (common in bank statements) far better than PyPDF2.

### Config env-var interpolation
`pydantic-settings` does not expand `${ENV_VAR}` tokens inside YAML files natively — PyYAML loads them as literal strings. The config loader in `src/bank_agent_llm/config.py` calls `os.path.expandvars` on the raw YAML string before passing it to the YAML parser. Secrets are stored in `.env` and loaded via `python-dotenv` before config parsing.

### Tiered categorization (rules first, LLM fallback)
LLMs are slow and non-deterministic for high-volume classification. A keyword/regex rules engine handles the predictable majority of transactions instantly and for free. Ollama is invoked only for descriptions that no rule matches, making it optional infrastructure rather than a hard dependency.
