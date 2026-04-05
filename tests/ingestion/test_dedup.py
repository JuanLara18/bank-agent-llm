"""Tests for file deduplication."""

from pathlib import Path

from bank_agent_llm.ingestion.dedup import compute_file_hash


def test_hash_is_64_char_hex(tmp_path: Path) -> None:
    f = tmp_path / "file.pdf"
    f.write_bytes(b"content")
    h = compute_file_hash(f)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_same_content_same_hash(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"same content")
    b.write_bytes(b"same content")
    assert compute_file_hash(a) == compute_file_hash(b)


def test_different_content_different_hash(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"content A")
    b.write_bytes(b"content B")
    assert compute_file_hash(a) != compute_file_hash(b)


def test_empty_file_has_stable_hash(tmp_path: Path) -> None:
    f = tmp_path / "empty.pdf"
    f.write_bytes(b"")
    h1 = compute_file_hash(f)
    h2 = compute_file_hash(f)
    assert h1 == h2
