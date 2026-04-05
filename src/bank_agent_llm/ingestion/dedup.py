"""File deduplication — prevent re-processing already-imported statements."""

from __future__ import annotations

import hashlib
from pathlib import Path


def compute_file_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents.

    Reads the file in 8 KB chunks to handle large PDFs without loading
    the entire file into memory.
    """
    sha256 = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
