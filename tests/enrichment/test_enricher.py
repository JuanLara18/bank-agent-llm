"""Integration tests for TransactionEnricher (rules layer, no Ollama)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bank_agent_llm.config import clear_settings_cache
from bank_agent_llm.storage.models import Base, Transaction, Account


@pytest.fixture(autouse=True)
def clear_cache() -> None:
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


@pytest.fixture
def db_session(config_file: Path):
    from bank_agent_llm.config import get_settings
    from bank_agent_llm.storage import database as db_module

    settings = get_settings(config_file)
    engine = create_engine(settings.database.url)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    db_module._engine = engine
    db_module._SessionFactory = SessionFactory

    session = SessionFactory()
    yield session
    session.close()
    db_module._engine = None
    db_module._SessionFactory = None


def _make_tx(session, raw_description: str, direction: str = "debit", amount: float = 10000.0) -> Transaction:
    # Ensure account exists
    from bank_agent_llm.storage.repository import AccountRepository
    acc = AccountRepository(session).get_or_create(bank_name="Test", account_number="1234")
    import hashlib
    desc_hash = hashlib.sha256(raw_description.encode()).hexdigest()
    tx = Transaction(
        account_id=acc.id,
        date=date(2026, 3, 1),
        amount=Decimal(str(amount)),
        direction=direction,
        raw_description=raw_description,
        source_file="test.pdf",
        description_hash=desc_hash,
        position_in_statement=0,
    )
    session.add(tx)
    session.flush()
    return tx


# ── Rules-only enrichment (no Ollama) ────────────────────────────────────────

def test_enrich_tags_uber(db_session, config_file):
    from bank_agent_llm.config import get_settings
    from bank_agent_llm.enrichment.enricher import TransactionEnricher

    tx = _make_tx(db_session, "UBER RIDES", "debit")
    enricher = TransactionEnricher(get_settings(config_file))

    with patch.object(enricher._ollama, "is_available", return_value=False):
        result = enricher.enrich(db_session)

    assert result.by_rules == 1
    assert result.by_llm == 0
    db_session.refresh(tx)
    assert "uber" in tx.tags
    assert "transporte" in tx.tags
    assert tx.merchant_name == "Uber"
    assert tx.tag_source == "keyword_rule"


def test_enrich_tags_credit_pago(db_session, config_file):
    from bank_agent_llm.config import get_settings
    from bank_agent_llm.enrichment.enricher import TransactionEnricher

    tx = _make_tx(db_session, "ABONO WOMPI/PSE", "credit")
    enricher = TransactionEnricher(get_settings(config_file))

    with patch.object(enricher._ollama, "is_available", return_value=False):
        result = enricher.enrich(db_session)

    db_session.refresh(tx)
    assert "pago-tarjeta" in tx.tags
    assert tx.tag_source == "keyword_rule"


def test_enrich_unknown_goes_pending_when_no_llm(db_session, config_file):
    from bank_agent_llm.config import get_settings
    from bank_agent_llm.enrichment.enricher import TransactionEnricher

    tx = _make_tx(db_session, "ZXQWERTY UNKNOWN MERCHANT", "debit")
    enricher = TransactionEnricher(get_settings(config_file))

    with patch.object(enricher._ollama, "is_available", return_value=False):
        result = enricher.enrich(db_session)

    assert result.pending >= 1
    assert result.llm_unavailable is True
    db_session.refresh(tx)
    assert tx.tag_source == "pending"  # not modified


def test_enrich_skips_manual(db_session, config_file):
    from bank_agent_llm.config import get_settings
    from bank_agent_llm.enrichment.enricher import TransactionEnricher

    tx = _make_tx(db_session, "UBER RIDES", "debit")
    tx.tag_source = "manual"
    tx.tags = ["custom-tag"]
    db_session.flush()

    enricher = TransactionEnricher(get_settings(config_file))
    with patch.object(enricher._ollama, "is_available", return_value=False):
        result = enricher.enrich(db_session)

    # Manual transactions are excluded at query level — total=0, not loaded at all
    assert result.total == 0
    db_session.refresh(tx)
    assert tx.tags == ["custom-tag"]  # unchanged


def test_enrich_multiple_transactions(db_session, config_file):
    from bank_agent_llm.config import get_settings
    from bank_agent_llm.enrichment.enricher import TransactionEnricher

    descriptions = [
        ("NETFLIX", "debit"),
        ("INTERESES CORRIENTES", "debit"),
        ("GMF GRAVAMEN MOVIMIENTO FINANC", "debit"),
        ("ABONO WOMPI/PSE", "credit"),
        ("TIENDA D1 CALLE 80", "debit"),
    ]
    txs = [_make_tx(db_session, d, dir_) for d, dir_ in descriptions]

    enricher = TransactionEnricher(get_settings(config_file))
    with patch.object(enricher._ollama, "is_available", return_value=False):
        result = enricher.enrich(db_session)

    assert result.by_rules == 5
    assert result.pending == 0

    for tx in txs:
        db_session.refresh(tx)
        assert tx.tags, f"No tags assigned to {tx.raw_description}"
        assert tx.tag_source in ("keyword_rule", "direction_rule")


def test_enrich_idempotent_by_default(db_session, config_file):
    """Running enrich twice without force should not re-tag."""
    from bank_agent_llm.config import get_settings
    from bank_agent_llm.enrichment.enricher import TransactionEnricher

    tx = _make_tx(db_session, "UBER RIDES", "debit")
    enricher = TransactionEnricher(get_settings(config_file))

    with patch.object(enricher._ollama, "is_available", return_value=False):
        r1 = enricher.enrich(db_session)
        r2 = enricher.enrich(db_session)

    assert r1.by_rules == 1
    # Second run finds nothing to process (already tagged, excluded at query level)
    assert r2.total == 0
    assert r2.by_rules == 0
