# Architecture

## Pipeline overview

```mermaid
flowchart LR
    A([Email Accounts\nIMAP]) --> B[Ingestion]
    B --> C{Parser Factory}
    C --> D[Bank A]
    C --> E[Bank B]
    C --> F[Bank N]
    D & E & F --> G[Enrichment\nOllama]
    G --> H[(Database)]
    H --> I[Power BI]
    H --> J[CLI Chat]
```

## Layer detail

```mermaid
flowchart TD
    subgraph ing["Ingestion — src/ingestion/"]
        direction LR
        IC[IMAP Client] --> AF[Attachment Filter]
        AF --> DR[Dedup Registry]
        DR --> FS[data/raw/]
    end

    subgraph par["Parsers — src/parsers/"]
        direction LR
        PF[ParserFactory\nget_parser&#40;file&#41;] --> BA[BankA Parser]
        PF --> BB[BankB Parser]
        PF --> BN[... Parser]
    end

    subgraph enr["Enrichment — src/enrichment/"]
        direction LR
        OC[Ollama Client] --> CAT[Categorizer]
        CAT --> CC[Category Cache\navoid re-calling LLM]
    end

    subgraph sto["Storage — src/storage/"]
        direction LR
        MOD[SQLAlchemy Models] --- REP[Repository Layer]
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
        decimal amount
        string direction
        string raw_description
        string normalized_description
        int category_id FK
        float category_confidence
        string source_file
        string description_hash
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

    accounts ||--o{ transactions : has
    categories ||--o{ transactions : classifies
    categories ||--o{ categories : parent
```

## Parser pattern

```mermaid
classDiagram
    class BankParser {
        <<abstract>>
        +bank_name() str
        +can_parse(file_path) bool
        +parse(file_path) list~RawTransaction~
    }

    class ParserFactory {
        -_parsers list~BankParser~
        +get_parser(file_path) BankParser
        +supported_banks() list~str~
    }

    class BankAParser {
        +bank_name = "BankA"
        +SIGNATURE = "..."
        +can_parse(file_path) bool
        +parse(file_path) list~RawTransaction~
    }

    class BankBParser {
        +bank_name = "BankB"
        +can_parse(file_path) bool
        +parse(file_path) list~RawTransaction~
    }

    BankParser <|-- BankAParser
    BankParser <|-- BankBParser
    ParserFactory o-- BankParser
```

## CLI architecture

```mermaid
flowchart TD
    CLI[bank-agent CLI\ncli.py] --> PL[Pipeline\npipeline.py]
    PL --> ING[ingestion/]
    PL --> PAR[parsers/]
    PL --> ENR[enrichment/]
    PL --> STO[storage/]
    CLI --> CHAT[chat/]
    CLI --> CFG[config-check\nconfig.py]
    CLI --> DB[db migrate\nalembic]
```

The CLI is a thin layer. Every command delegates immediately to `Pipeline` or a module. This keeps the library usable independently of the CLI.

## Architectural decisions

### SQLite as default database
Zero setup for new users. Power BI connects via ODBC. Switchable to PostgreSQL via one config line.

### Direct Ollama API over LangChain
Fewer dependencies, full control over prompts, no framework abstractions between the LLM call and the code.

### imapclient over stdlib imaplib
`imapclient` provides a clean, Pythonic API with proper connection management. `imaplib` is verbose and error-prone for multi-folder, multi-account setups.

### tenacity for retries
Both IMAP connections and Ollama calls are network operations that can transiently fail. `tenacity` handles exponential backoff with one decorator — no manual retry loops.

### pdfplumber as primary PDF library
Handles multi-column, tabular PDF layouts (common in bank statements) far better than PyPDF2, which is limited to simple text extraction.
