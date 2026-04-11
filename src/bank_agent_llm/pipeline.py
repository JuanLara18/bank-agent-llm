"""High-level Pipeline — primary entry point for library users.

Usage as a library:
    from bank_agent_llm import Pipeline

    pipeline = Pipeline()
    pipeline.import_files("./my-statements/")
    pipeline.run()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Summary returned by Pipeline.fetch()."""

    accounts_checked: int = 0
    emails_scanned: int = 0
    emails_new: int = 0
    attachments_downloaded: int = 0
    errors: list[str] = field(default_factory=list)
    discovered_patterns: list[dict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class ImportResult:
    """Summary returned by Pipeline.import_files()."""

    scanned: int = 0
    imported: int = 0       # new transactions stored
    skipped_dedup: int = 0  # files already in DB
    skipped_no_parser: int = 0
    empty_parses: int = 0   # parser matched but returned 0 transactions
    errors: int = 0
    error_details: list[str] = field(default_factory=list)
    skipped_details: list[tuple[str, str]] = field(default_factory=list)
    empty_parse_details: list[tuple[str, str]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.errors == 0


class Pipeline:
    """Orchestrates the full fetch → parse → enrich → store flow.

    This class is the public API for using bank-agent-llm as a library.
    CLI commands delegate to this class internally.

    Args:
        config_path: Path to config.yaml. Defaults to ``config/config.yaml``
                     relative to the current working directory.
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _get_settings(self):  # type: ignore[return]
        from bank_agent_llm.config import get_settings
        return get_settings(self._config_path)

    def _init_db(self) -> None:
        from bank_agent_llm.storage.database import init_engine
        init_engine(self._get_settings().database.url)

    # ─── Public API ───────────────────────────────────────────────────────────

    def import_files(self, path: str | Path) -> ImportResult:
        """Parse statement files from a local path, bypassing email ingestion.

        Scans path for supported files (.pdf, .xlsx), skips already-imported
        ones by SHA-256 hash, routes each file through the ParserFactory, and
        stores the extracted transactions.

        Args:
            path: A single statement file or a directory (scanned recursively).

        Returns:
            ImportResult with counts for each outcome.

        Raises:
            FileNotFoundError: If path does not exist.
        """
        from bank_agent_llm.ingestion.dedup import compute_file_hash
        from bank_agent_llm.ingestion.file_scanner import scan
        from bank_agent_llm.parsers.factory import ParserFactory, UnsupportedBankError
        from bank_agent_llm.storage.database import get_session
        from bank_agent_llm.storage.repository import (
            AccountRepository,
            FileProcessingRunRepository,
            TransactionRepository,
        )

        path = Path(path)
        self._init_db()
        settings = self._get_settings()

        files = scan(path)
        result = ImportResult(scanned=len(files))
        factory = ParserFactory()
        passwords = settings.pipeline.pdf_passwords

        logger.info("Scanning %s — found %d file(s)", path, len(files))

        for file_path in files:
            file_hash = compute_file_hash(file_path)

            with get_session() as session:
                file_repo = FileProcessingRunRepository(session)

                if file_repo.is_processed(file_hash):
                    logger.debug("Already imported, skipping: %s", file_path.name)
                    result.skipped_dedup += 1
                    continue

                try:
                    parser = factory.get_parser(file_path, passwords=passwords)
                except UnsupportedBankError:
                    reason = "no parser matched first-page signature"
                    logger.warning("No parser for: %s (%s)", file_path.name, reason)
                    file_repo.record_outcome(
                        str(file_path), file_hash, "skipped",
                        error_message=reason,
                    )
                    result.skipped_no_parser += 1
                    result.skipped_details.append((file_path.name, reason))
                    continue

                try:
                    raw_transactions = parser.parse(file_path)
                    tx_repo = TransactionRepository(session)
                    acc_repo = AccountRepository(session)

                    # Use account_number from first transaction if available,
                    # fall back to file hash prefix as stable identifier.
                    extracted_account = (
                        raw_transactions[0].account_number
                        if raw_transactions and raw_transactions[0].account_number
                        else None
                    )
                    account = acc_repo.get_or_create(
                        bank_name=parser.bank_name,
                        account_number=extracted_account or file_hash[:16],
                    )

                    new_count = 0
                    for raw in raw_transactions:
                        import hashlib
                        tx_hash = hashlib.sha256(raw.raw_description.encode()).hexdigest()
                        from bank_agent_llm.storage.models import Transaction
                        tx = Transaction(
                            account_id=account.id,
                            date=raw.date,
                            amount=raw.amount,
                            currency=raw.currency,
                            direction=raw.direction.value,
                            raw_description=raw.raw_description,
                            source_file=str(file_path),
                            description_hash=tx_hash,
                            position_in_statement=raw.position_in_statement,
                        )
                        _, created = tx_repo.add_or_skip(tx)
                        if created:
                            new_count += 1

                    file_repo.record_outcome(
                        str(file_path), file_hash, "success",
                        bank_name=parser.bank_name,
                        transaction_count=new_count,
                    )
                    result.imported += new_count
                    logger.info(
                        "Imported %d transaction(s) from %s (%s)",
                        new_count, file_path.name, parser.bank_name,
                    )
                    if not raw_transactions:
                        reason = f"{parser.bank_name} parser returned 0 rows"
                        logger.warning("Empty parse: %s (%s)", file_path.name, reason)
                        result.empty_parses += 1
                        result.empty_parse_details.append((file_path.name, reason))

                except Exception as exc:  # noqa: BLE001
                    msg = f"{file_path.name}: {exc}"
                    logger.error("Failed to parse %s", msg)
                    file_repo.record_outcome(
                        str(file_path), file_hash, "error", error_message=str(exc)
                    )
                    result.errors += 1
                    result.error_details.append(msg)

        return result

    def run(self, *, fetch: bool = True, parse: bool = True, enrich: bool = True) -> None:
        """Execute the pipeline end-to-end.

        Args:
            fetch:  Download new statement attachments from email accounts.
            parse:  Parse downloaded files into normalised transactions.
            enrich: Categorise transactions via the local Ollama model.
        """
        logger.info("Pipeline run started (fetch=%s parse=%s enrich=%s)", fetch, parse, enrich)
        raise NotImplementedError("run() not yet implemented — see docs/roadmap.md (M6)")

    def fetch(self, *, discover: bool = False) -> FetchResult:
        """Download new statement attachments from all configured email accounts.

        For Gmail accounts with OAuth2 credentials (config/gmail_credentials.json),
        uses the Gmail API. For other accounts, uses IMAP.

        Args:
            discover: If True, scan and report email patterns without downloading.

        Returns:
            FetchResult with counts per outcome.
        """
        from bank_agent_llm.ingestion.gmail_client import GmailClient
        from bank_agent_llm.ingestion.imap_client import ImapClient
        from bank_agent_llm.storage.database import get_session
        from bank_agent_llm.storage.repository import ProcessedEmailRepository

        self._init_db()
        settings = self._get_settings()
        raw_dir = Path(settings.pipeline.raw_data_dir)
        config_dir = Path(self._config_path).parent if self._config_path else Path("config")
        result = FetchResult()

        gmail_creds = config_dir / "gmail_credentials.json"
        gmail_token = config_dir / "gmail_token.json"

        # ── Gmail OAuth2 accounts ─────────────────────────────────────────────
        gmail_accounts = [a for a in settings.email_accounts if "gmail" in a.imap_host.lower()]
        if gmail_creds.exists() and gmail_accounts:
            for account_cfg in gmail_accounts:
                result.accounts_checked += 1
                since_year = 2022  # go back to 2022 for initial import
                client = GmailClient(
                    credentials_path=gmail_creds,
                    token_path=gmail_token,
                    account_name=account_cfg.name,
                    since_year=since_year,
                )
                with get_session() as session:
                    repo = ProcessedEmailRepository(session)
                    if discover:
                        account_result = client.discover()
                        result.discovered_patterns.extend(account_result.discovered)
                    else:
                        account_result = client.fetch(
                            dest_dir=raw_dir,
                            processed_repo=repo,
                            subject_filter=account_cfg.subject_keywords,
                        )
                    session.commit()

                result.emails_scanned += account_result.emails_scanned
                result.emails_new += account_result.emails_new
                result.attachments_downloaded += account_result.attachments_downloaded
                result.errors.extend(account_result.errors)

        # ── IMAP accounts (non-Gmail or Gmail without OAuth creds) ────────────
        imap_accounts = [
            a for a in settings.email_accounts
            if not ("gmail" in a.imap_host.lower() and gmail_creds.exists())
        ]
        for account_cfg in imap_accounts:
            if not account_cfg.password:
                logger.warning(
                    "Account %r has no password configured — skipping. "
                    "Set %s in your .env file.",
                    account_cfg.name,
                    f"EMAIL_{account_cfg.name.upper()}_PASS",
                )
                continue

            result.accounts_checked += 1
            client = ImapClient(
                host=account_cfg.imap_host,
                port=account_cfg.imap_port,
                username=account_cfg.username,
                password=account_cfg.password,
                use_ssl=account_cfg.use_ssl,
                folders=account_cfg.folders,
                subject_keywords=account_cfg.subject_keywords,
                lookback_days=settings.pipeline.initial_lookback_days,
            )
            with get_session() as session:
                repo = ProcessedEmailRepository(session)
                account_result = client.fetch(
                    dest_dir=raw_dir,
                    processed_repo=repo,
                    account_name=account_cfg.name,
                )
                session.commit()

            result.emails_scanned += account_result.emails_scanned
            result.emails_new += account_result.emails_new
            result.attachments_downloaded += account_result.attachments_downloaded
            result.errors.extend(account_result.errors)

        if not settings.email_accounts and not gmail_creds.exists():
            logger.warning(
                "No email accounts configured and no gmail_credentials.json found."
            )

        return result

    def parse(self) -> None:
        """Parse any unprocessed statement files in the raw data directory."""
        raise NotImplementedError("parse() not yet implemented — see docs/roadmap.md (M3)")

    def enrich(self, *, force: bool = False) -> EnrichResult:  # type: ignore[name-defined]
        """Tag all pending transactions using rules engine and optional Ollama.

        Args:
            force: Re-tag already-tagged transactions (skips manual ones).

        Returns:
            EnrichResult with counts per tagging source.
        """
        from bank_agent_llm.enrichment.enricher import TransactionEnricher
        from bank_agent_llm.storage.database import get_session

        self._init_db()
        enricher = TransactionEnricher(self._get_settings())

        with get_session() as session:
            return enricher.enrich(session, force=force)

    def purge(self, before: str) -> None:
        """Delete all transactions with a date before the given value.

        Args:
            before: ISO date string (YYYY-MM-DD).
        """
        from datetime import date

        self._init_db()
        try:
            cutoff = date.fromisoformat(before)
        except ValueError as exc:
            raise ValueError(f"Invalid date format: {before!r}. Expected YYYY-MM-DD.") from exc

        from bank_agent_llm.storage.database import get_session
        from bank_agent_llm.storage.repository import TransactionRepository

        with get_session() as session:
            deleted = TransactionRepository(session).delete_before(cutoff)
        logger.info("Purged %d transaction(s) before %s", deleted, before)
