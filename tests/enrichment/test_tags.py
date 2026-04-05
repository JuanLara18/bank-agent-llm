"""Tests for the tag taxonomy loader."""
from __future__ import annotations

from bank_agent_llm.enrichment.tags import get_taxonomy


def test_taxonomy_loads_without_error() -> None:
    tx = get_taxonomy()
    assert len(tx.all_ids()) > 10


def test_parent_tags_present() -> None:
    tx = get_taxonomy()
    for tag_id in ("comida", "transporte", "entretenimiento", "banco", "pago-tarjeta"):
        assert tag_id in tx.all_ids(), f"Missing top-level tag: {tag_id}"


def test_leaf_tags_have_parent() -> None:
    tx = get_taxonomy()
    assert tx.parent_of("restaurante") == "comida"
    assert tx.parent_of("uber") == "transporte"
    assert tx.parent_of("streaming") == "entretenimiento"
    assert tx.parent_of("intereses") == "banco"


def test_is_expense_true_for_spending_tags() -> None:
    tx = get_taxonomy()
    for tag_id in ("comida", "restaurante", "transporte", "uber", "banco"):
        assert tx.is_expense(tag_id), f"Expected {tag_id} to be expense"


def test_is_expense_false_for_non_expense_tags() -> None:
    tx = get_taxonomy()
    for tag_id in ("pago-tarjeta", "transferencia", "ingreso"):
        assert not tx.is_expense(tag_id), f"Expected {tag_id} to be non-expense"


def test_primary_tag_prefers_leaf() -> None:
    tx = get_taxonomy()
    # ["comida", "restaurante"] → leaf "restaurante" is preferred
    assert tx.primary_tag(["comida", "restaurante"]) == "restaurante"


def test_primary_tag_single_item() -> None:
    tx = get_taxonomy()
    assert tx.primary_tag(["uber"]) == "uber"


def test_primary_tag_empty_returns_none() -> None:
    tx = get_taxonomy()
    assert tx.primary_tag([]) is None


def test_validate_strips_unknown_tags() -> None:
    tx = get_taxonomy()
    result = tx.validate(["restaurante", "nonexistent_tag"])
    assert result == ["restaurante"]


def test_display_name() -> None:
    tx = get_taxonomy()
    assert tx.display_name("comida") == "Alimentación"
    assert tx.display_name("uber") == "Uber / Didi"
