"""ParserFactory: routes a file to the correct BankParser implementation."""

from __future__ import annotations

from pathlib import Path

from bank_agent_llm.parsers.bancolombia import BancolombiaParser
from bank_agent_llm.parsers.bancolombia_savings import BancolombiaSavingsParser
from bank_agent_llm.parsers.base import BankParser, ParseError
from bank_agent_llm.parsers.falabella import FalabellaParser
from bank_agent_llm.parsers.scotiabank import ScotiabankParser

# Parser classes registered in priority order (more specific signatures first).
# BancolombiaSavingsParser goes before BancolombiaParser because the savings
# layout is distinct and its signature is more specific.
# ParserFactory instantiates them with passwords at call time.
_PARSER_CLASSES = [
    BancolombiaSavingsParser,
    BancolombiaParser,
    FalabellaParser,
    ScotiabankParser,
]


class UnsupportedBankError(ParseError):
    """Raised when no parser can handle the given file."""

    def __init__(self, file_path: Path) -> None:
        super().__init__(
            f"No parser found for '{file_path.name}'. "
            "See docs/adding-a-parser.md to add support for this bank."
        )


_HINT_MAX_PAGES = 3


def _extract_pdf_hint(file_path: Path, passwords: list[str] | None = None) -> str:
    """Extract text from the first few pages of a PDF for use as a parser hint.

    Reads up to ``_HINT_MAX_PAGES`` pages so that signature strings which
    occasionally get pushed past page 1 (e.g. the Bancolombia footer on
    long savings statements) still appear in the hint. Tries without a
    password first, then each configured password in order for encrypted
    PDFs. Returns empty string on any failure.

    Extracted once per file so parsers don't reopen the document.
    """
    if file_path.suffix.lower() != ".pdf":
        return ""

    try:
        import pdfplumber  # noqa: PLC0415 — lazy import to keep startup fast

        candidates: list[str | None] = [None, *(passwords or [])]
        for pwd in candidates:
            try:
                kwargs = {"password": pwd} if pwd else {}
                with pdfplumber.open(file_path, **kwargs) as pdf:  # type: ignore[arg-type]
                    if not pdf.pages:
                        return ""
                    parts = [
                        page.extract_text() or ""
                        for page in pdf.pages[:_HINT_MAX_PAGES]
                    ]
                    text = "\n".join(parts)
                    if text.strip():
                        return text
            except Exception:  # noqa: BLE001
                continue

    except Exception:  # noqa: BLE001
        pass

    return ""


class ParserFactory:
    """Routes a statement file to the correct BankParser."""

    def __init__(self, parsers: list[BankParser] | None = None) -> None:
        # Allow injecting pre-built parser instances (e.g. in tests)
        self._parsers = parsers  # None = build from _PARSER_CLASSES at call time

    def _build_parsers(self, passwords: list[str] | None) -> list[BankParser]:
        """Instantiate registered parsers with the given passwords."""
        if self._parsers is not None:
            return self._parsers
        result: list[BankParser] = []
        for cls in _PARSER_CLASSES:
            try:
                result.append(cls(passwords=passwords))  # type: ignore[call-arg]
            except TypeError:
                result.append(cls())  # ScotiabankParser has no passwords arg
        return result

    def get_parser(
        self, file_path: Path, *, passwords: list[str] | None = None
    ) -> BankParser:
        """Return the first parser that can handle the file.

        Extracts first-page text once (trying passwords for encrypted PDFs)
        and passes it as a hint to each parser's can_parse() to avoid
        redundant file opens.

        Args:
            file_path: Path to the statement file.
            passwords: List of passwords to try for encrypted PDFs,
                       taken from ``settings.pipeline.pdf_passwords``.

        Raises:
            UnsupportedBankError: If no registered parser matches.
        """
        hint = _extract_pdf_hint(file_path, passwords=passwords)
        for parser in self._build_parsers(passwords):
            if parser.can_parse(file_path, hint=hint):
                return parser
        raise UnsupportedBankError(file_path)

    @property
    def supported_banks(self) -> list[str]:
        """List of bank names for which parsers are registered."""
        return [p.bank_name for p in self._build_parsers(None)]
