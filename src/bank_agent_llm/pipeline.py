"""High-level Pipeline — primary entry point for library users.

Usage as a library:
    from bank_agent_llm import Pipeline

    pipeline = Pipeline()
    pipeline.run()
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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
        # Modules are initialised lazily when run() is called so that
        # importing the library never has side effects.

    def run(self, *, fetch: bool = True, parse: bool = True, enrich: bool = True) -> None:
        """Execute the pipeline end-to-end.

        Args:
            fetch:  Download new statement attachments from email accounts.
            parse:  Parse downloaded files into normalised transactions.
            enrich: Categorise transactions via the local Ollama model.
        """
        logger.info("Pipeline run started (fetch=%s parse=%s enrich=%s)", fetch, parse, enrich)
        # TODO: wire up modules in M2, M3, M4
        raise NotImplementedError("Pipeline not yet implemented — see docs/roadmap.md")

    def fetch(self) -> None:
        """Download new statement attachments from all configured email accounts."""
        raise NotImplementedError

    def parse(self) -> None:
        """Parse any unprocessed statement files in the raw data directory."""
        raise NotImplementedError

    def enrich(self) -> None:
        """Categorise uncategorised transactions using the local Ollama model."""
        raise NotImplementedError

    def import_files(self, path: str | Path) -> None:
        """Parse statement files from a local path, bypassing email ingestion.

        This is the primary ingestion method for users who download statements
        manually from their bank's web portal or have an existing folder of PDFs.

        Args:
            path: A single statement file or a directory. Directories are
                  scanned recursively for supported file types (.pdf, .xlsx).

        Raises:
            FileNotFoundError: If path does not exist.
            UnsupportedBankError: If a file cannot be matched to any parser.
        """
        # TODO: implement in M2
        raise NotImplementedError

    def purge(self, before: str) -> None:
        """Delete all transactions with a date before the given value.

        Args:
            before: ISO date string (YYYY-MM-DD). Transactions strictly before
                    this date are deleted. The operation is irreversible.
        """
        # TODO: implement in M5 (storage layer)
        raise NotImplementedError
