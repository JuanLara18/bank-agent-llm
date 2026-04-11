"""Integration tests for Pipeline.import_files()."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bank_agent_llm.config import clear_settings_cache
from bank_agent_llm.storage.models import Base


@pytest.fixture(autouse=True)
def clear_config_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.dump({"database": {"url": f"sqlite:///{db_path}"}}),
        encoding="utf-8",
    )
    return cfg


@pytest.fixture(autouse=True)
def setup_db(config_file: Path) -> None:
    """Create schema in the test database."""
    from bank_agent_llm.config import get_settings
    settings = get_settings(config_file)
    engine = create_engine(settings.database.url)
    Base.metadata.create_all(engine)

    from bank_agent_llm.storage import database as db_module
    db_module._engine = engine
    db_module._SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    yield
    db_module._engine = None
    db_module._SessionFactory = None


def test_import_raises_on_missing_path(config_file: Path) -> None:
    from bank_agent_llm.pipeline import Pipeline
    with pytest.raises(FileNotFoundError):
        Pipeline(config_path=str(config_file)).import_files("/nonexistent/path")


def test_import_empty_directory(tmp_path: Path, config_file: Path) -> None:
    from bank_agent_llm.pipeline import Pipeline
    result = Pipeline(config_path=str(config_file)).import_files(tmp_path)
    assert result.scanned == 0
    assert result.imported == 0


def test_import_unsupported_file_is_skipped(tmp_path: Path, config_file: Path) -> None:
    (tmp_path / "notes.txt").write_bytes(b"not a statement")
    from bank_agent_llm.pipeline import Pipeline
    result = Pipeline(config_path=str(config_file)).import_files(tmp_path)
    assert result.scanned == 0


def test_import_pdf_with_no_parser_increments_skipped(
    tmp_path: Path, config_file: Path
) -> None:
    pdf = tmp_path / "unknown_bank.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    from bank_agent_llm.pipeline import Pipeline
    result = Pipeline(config_path=str(config_file)).import_files(tmp_path)
    assert result.scanned == 1
    assert result.skipped_no_parser == 1
    assert result.imported == 0
    assert len(result.skipped_details) == 1
    name, reason = result.skipped_details[0]
    assert name == "unknown_bank.pdf"
    assert reason  # non-empty explanation


def test_skipped_file_is_retried_on_next_run(tmp_path: Path, config_file: Path) -> None:
    """A file that had no parser on the first run must be retried on the next
    run — so that adding or fixing a parser automatically picks it up."""
    pdf = tmp_path / "unknown_bank.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    from bank_agent_llm.pipeline import Pipeline
    pipeline = Pipeline(config_path=str(config_file))
    r1 = pipeline.import_files(tmp_path)
    r2 = pipeline.import_files(tmp_path)
    assert r1.skipped_no_parser == 1
    assert r2.scanned == 1
    assert r2.skipped_dedup == 0
    assert r2.skipped_no_parser == 1
