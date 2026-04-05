"""File scanner — find statement files in a local path.

Supports single files or directories (recursive). Only files with
extensions declared in SUPPORTED_EXTENSIONS are returned.
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".xlsx", ".xls", ".csv"})


def scan(path: Path) -> list[Path]:
    """Return all supported statement files at path, sorted by name.

    Args:
        path: A single file or a directory to scan recursively.

    Returns:
        List of absolute file paths with supported extensions.

    Raises:
        FileNotFoundError: If path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_file():
        return [path.resolve()] if path.suffix.lower() in SUPPORTED_EXTENSIONS else []

    return sorted(
        p.resolve()
        for p in path.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
