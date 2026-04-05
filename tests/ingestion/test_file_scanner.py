"""Tests for file scanner."""

from pathlib import Path

import pytest

from bank_agent_llm.ingestion.file_scanner import SUPPORTED_EXTENSIONS, scan


def test_raises_on_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scan(tmp_path / "nonexistent")


def test_single_pdf_file(tmp_path: Path) -> None:
    pdf = tmp_path / "statement.pdf"
    pdf.touch()
    assert scan(pdf) == [pdf.resolve()]


def test_single_unsupported_file(tmp_path: Path) -> None:
    txt = tmp_path / "notes.txt"
    txt.touch()
    assert scan(txt) == []


def test_directory_returns_supported_files_only(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").touch()
    (tmp_path / "b.xlsx").touch()
    (tmp_path / "c.txt").touch()
    (tmp_path / "d.csv").touch()
    result = scan(tmp_path)
    names = {p.name for p in result}
    assert names == {"a.pdf", "b.xlsx", "d.csv"}


def test_directory_scans_recursively(tmp_path: Path) -> None:
    sub = tmp_path / "bank_a"
    sub.mkdir()
    (sub / "jan.pdf").touch()
    (tmp_path / "feb.pdf").touch()
    result = scan(tmp_path)
    assert len(result) == 2


def test_results_are_sorted(tmp_path: Path) -> None:
    for name in ["c.pdf", "a.pdf", "b.pdf"]:
        (tmp_path / name).touch()
    result = scan(tmp_path)
    assert [p.name for p in result] == ["a.pdf", "b.pdf", "c.pdf"]


def test_all_supported_extensions_detected(tmp_path: Path) -> None:
    for ext in SUPPORTED_EXTENSIONS:
        (tmp_path / f"file{ext}").touch()
    assert len(scan(tmp_path)) == len(SUPPORTED_EXTENSIONS)
