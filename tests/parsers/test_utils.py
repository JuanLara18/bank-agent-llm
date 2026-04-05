"""Tests for parser shared utilities."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bank_agent_llm.parsers._utils import (
    dedouble,
    group_words_by_row,
    is_date,
    parse_cop,
    parse_date,
    row_tokens,
)


# ── is_date ──────────────────────────────────────────────────────────────────

def test_is_date_valid() -> None:
    assert is_date("01/02/2026") is True


def test_is_date_invalid_format() -> None:
    assert is_date("2026-02-01") is False
    assert is_date("1/2/2026") is False
    assert is_date("hello") is False


# ── parse_date ────────────────────────────────────────────────────────────────

def test_parse_date_basic() -> None:
    from datetime import date
    assert parse_date("11/02/2026") == date(2026, 2, 11)


# ── parse_cop ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("9.600,00", Decimal("9600.00")),
    ("-2.085.486,00", Decimal("-2085486.00")),
    ("41.193", Decimal("41193")),
    ("$9.600,00", Decimal("9600.00")),
    ("--$944.714,94", Decimal("-944714.94")),
    ("0,00", Decimal("0.00")),
])
def test_parse_cop(text: str, expected: Decimal) -> None:
    assert parse_cop(text) == expected


def test_parse_cop_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_cop("not-a-number")


# ── dedouble ──────────────────────────────────────────────────────────────────

def test_dedouble_fully_doubled() -> None:
    assert dedouble("TTaarrjjeettaa") == "Tarjeta"


def test_dedouble_single_char() -> None:
    assert dedouble("T") == "T"


def test_dedouble_not_doubled_returns_unchanged() -> None:
    assert dedouble("Tarjeta") == "Tarjeta"


def test_dedouble_odd_length_returns_unchanged() -> None:
    assert dedouble("ABC") == "ABC"


def test_dedouble_partially_doubled_returns_unchanged() -> None:
    # "AABc" — first pair is doubled but second is not
    assert dedouble("AABc") == "AABc"


# ── group_words_by_row ────────────────────────────────────────────────────────

def _word(text: str, x0: float, top: float) -> dict:
    return {"text": text, "x0": x0, "top": top}


def test_group_words_by_row_single_row() -> None:
    words = [_word("A", 10, 100), _word("B", 50, 100), _word("C", 90, 100)]
    rows = group_words_by_row(words)
    assert len(rows) == 1
    assert row_tokens(rows[0]) == ["A", "B", "C"]


def test_group_words_by_row_two_rows() -> None:
    words = [
        _word("A", 10, 100),
        _word("B", 50, 105),  # same row (within tolerance=3 → NO, diff=5 → new row)
        _word("C", 90, 200),
    ]
    rows = group_words_by_row(words, y_tolerance=3.0)
    assert len(rows) == 3


def test_group_words_by_row_within_tolerance() -> None:
    words = [_word("A", 10, 100), _word("B", 50, 102)]  # diff=2 ≤ 3
    rows = group_words_by_row(words, y_tolerance=3.0)
    assert len(rows) == 1


def test_group_words_by_row_empty() -> None:
    assert group_words_by_row([]) == []


def test_group_words_by_row_sorted_left_to_right() -> None:
    words = [_word("B", 50, 100), _word("A", 10, 100)]
    rows = group_words_by_row(words)
    assert row_tokens(rows[0]) == ["A", "B"]
