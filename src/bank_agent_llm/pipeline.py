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
class ImportResult:
    """Summary returned by Pipeline.import_files()."""

    scanned: int = 0
    imported: int = 0       # new transactions stored
    skipped_dedup: int = 0  # files already in DB
    skipped_no_parser: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

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
                    logger.warning("No parser for: %s", file_path.name)
                    file_repo.create(str(file_path), file_hash, "skipped")
                    result.skipped_no_parser += 1
                    continue

                try:
                    raw_transactions = parser.parse(file_path)
                    tx_repo = TransactionRepository(session)
                    acc_repo = AccountRepository(session)

                    account = acc_repo.get_or_create(
                        bank_name=parser.bank_name,
                        account_number=file_hash[:16],  # placeholder until parsers extract it
                    )

                    new_count = 0
                    for raw in raw_transactions:
                        import hashlib
                        tx_hash = hashlib.sha256(raw.raw_description.encode()).hexdigest()
                        from bank_agent_llm.storage.models import Transaction
                        tx = Transaction(
                            account_id=account.id,
                            date=raw.date,
                            transaction_time=raw.transaction_time,
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

                    file_repo.create(
                        str(file_path), file_hash, "success",
                        bank_name=parser.bank_name,
                        transaction_count=new_count,
                    )
                    result.imported += new_count
                    logger.info(
                        "Imported %d transaction(s) from %s (%s)",
                        new_count, file_path.name, parser.bank_name,
                    )

                except Exception as exc:  # noqa: BLE001
                    msg = f"{file_path.name}: {exc}"
                    logger.error("Failed to parse %s", msg)
                    file_repo.create(str(file_path), file_hash, "error", error_message=str(exc))
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

    def fetch(self) -> None:
        """Download new statement attachments from all configured email accounts."""
        raise NotImplementedError("fetch() not yet implemented — see docs/roadmap.md (M5)")

    def parse(self) -> None:
        """Parse any unprocessed statement files in the raw data directory."""
        raise NotImplementedError("parse() not yet implemented — see docs/roadmap.md (M3)")

    def enrich(self) -> None:
        """Categorise uncategorised transactions using the local Ollama model."""
        raise NotImplementedError("enrich() not yet implemented — see docs/roadmap.md (M4)")

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
