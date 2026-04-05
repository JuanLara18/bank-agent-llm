"""ParserFactory: routes a file to the correct BankParser implementation."""

from pathlib import Path

from bank_agent_llm.parsers.base import BankParser, ParseError

# Register new parsers here as they are implemented:
# from bank_agent_llm.parsers.bancolombia import BancolombiaParser
_PARSERS: list[BankParser] = [
    # BancolombiaParser(),
]


class UnsupportedBankError(ParseError):
    """Raised when no parser can handle the given file."""

    def __init__(self, file_path: Path) -> None:
        super().__init__(
            f"No parser found for '{file_path.name}'. "
            "See docs/adding-a-parser.md to add support for this bank."
        )


def _extract_pdf_hint(file_path: Path) -> str:
    """Extract first-page text from a PDF for use as a parser hint.

    Returns an empty string for non-PDF files or unreadable PDFs.
    Extracted once per file so parsers don't reopen the document.
    """
    if file_path.suffix.lower() != ".pdf":
        return ""
    try:
        import pdfplumber  # noqa: PLC0415 — lazy import to keep startup fast

        with pdfplumber.open(file_path) as pdf:
            if not pdf.pages:
                return ""
            return pdf.pages[0].extract_text() or ""
    except Exception:  # noqa: BLE001
        return ""


class ParserFactory:
    """Routes a statement file to the correct BankParser."""

    def __init__(self, parsers: list[BankParser] | None = None) -> None:
        self._parsers = parsers if parsers is not None else _PARSERS

    def get_parser(self, file_path: Path) -> BankParser:
        """Return the first parser that can handle the file.

        Extracts first-page text once and passes it as a hint to each
        parser's can_parse() to avoid redundant PDF opens.

        Raises:
            UnsupportedBankError: If no registered parser matches.
        """
        hint = _extract_pdf_hint(file_path)
        for parser in self._parsers:
            if parser.can_parse(file_path, hint=hint):
                return parser
        raise UnsupportedBankError(file_path)

    @property
    def supported_banks(self) -> list[str]:
        """List of bank names for which parsers are registered."""
        return [p.bank_name for p in self._parsers]
