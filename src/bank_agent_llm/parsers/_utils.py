"""Shared utilities for PDF-based bank parsers."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# DD/MM/YYYY
_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

# Matches doubled characters: TT → T, AA → A, etc. (Falabella encoding)
_DOUBLE_RE = re.compile(r"(.)\1")


def open_pdf(file_path: Path, passwords: list[str] | None = None):
    """Open a pdfplumber PDF, trying passwords if needed.

    Args:
        file_path: Path to the PDF.
        passwords: Passwords to try (in order) if the PDF is encrypted.

    Returns:
        An open pdfplumber.PDF context (caller must use as context manager or close).

    Raises:
        RuntimeError: If the PDF is encrypted and no password works.
    """
    import pdfplumber

    pdf = pdfplumber.open(str(file_path))
    if not pdf.pages:
        return pdf

    # Try to access first page — if encrypted, it will raise
    try:
        _ = pdf.pages[0].extract_text()
        return pdf
    except Exception:  # noqa: BLE001
        pdf.close()

    for pw in (passwords or []):
        try:
            pdf = pdfplumber.open(str(file_path), password=pw)
            _ = pdf.pages[0].extract_text()
            return pdf
        except Exception:  # noqa: BLE001
            pdf.close()

    raise RuntimeError(f"Could not open encrypted PDF: {file_path.name}")


def group_words_by_row(
    words: list[dict[str, Any]],
    y_tolerance: float = 3.0,
) -> list[list[dict[str, Any]]]:
    """Group pdfplumber word dicts into rows by their vertical (top) position.

    Args:
        words: List of word dicts from ``page.extract_words()``.
        y_tolerance: Words within this many points vertically are the same row.

    Returns:
        List of rows, each row is a list of word dicts sorted left-to-right.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    rows: list[list[dict[str, Any]]] = []
    current_row: list[dict[str, Any]] = [sorted_words[0]]
    current_top = sorted_words[0]["top"]

    for word in sorted_words[1:]:
        if abs(word["top"] - current_top) <= y_tolerance:
            current_row.append(word)
        else:
            rows.append(sorted(current_row, key=lambda w: w["x0"]))
            current_row = [word]
            current_top = word["top"]

    rows.append(sorted(current_row, key=lambda w: w["x0"]))
    return rows


def is_date(token: str) -> bool:
    """Return True if token looks like DD/MM/YYYY."""
    return bool(_DATE_RE.match(token))


def parse_date(token: str) -> date:
    """Parse DD/MM/YYYY into a date object."""
    day, month, year = token.split("/")
    return date(int(year), int(month), int(day))


def parse_cop(text: str) -> Decimal:
    """Parse a Colombian peso amount string to Decimal.

    Handles formats:
    - ``9.600,00``  →  9600.00
    - ``-2.085.486,00``  →  -2085486.00
    - ``41.193``  →  41193  (no decimal separator)
    - ``$9.600,00``  →  9600.00
    - ``--$944.714,94`` (Falabella doubled minus)

    Raises:
        ValueError: If the text cannot be parsed.
    """
    cleaned = text.strip()
    # Remove currency symbol
    cleaned = cleaned.replace("$", "").strip()
    # Collapse doubled minus signs (Falabella encoding artefact)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    # If comma exists → European format (period=thousands, comma=decimal)
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        # No comma — period is thousands separator only
        cleaned = cleaned.replace(".", "")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse COP amount: {text!r}") from exc


def dedouble(text: str) -> str:
    """Remove Falabella's double-character encoding.

    Falabella PDF headers encode each character twice:
    ``TTaarrjjeettaa``  →  ``Tarjeta``

    Only applies the reduction when *every* pair is doubled; otherwise
    returns the text unchanged (to avoid corrupting normal words).
    """
    if len(text) < 2:
        return text
    # Check all adjacent pairs are equal (strict doubled encoding)
    if len(text) % 2 == 0 and all(text[i] == text[i + 1] for i in range(0, len(text), 2)):
        return text[::2]
    return text


def row_tokens(row: list[dict[str, Any]]) -> list[str]:
    """Extract the text values from a row of word dicts."""
    return [w["text"] for w in row]
