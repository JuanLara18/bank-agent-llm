"""Tests for ParserFactory."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bank_agent_llm.parsers.base import BankParser, RawTransaction
from bank_agent_llm.parsers.factory import ParserFactory, UnsupportedBankError


def _make_mock_parser(bank_name: str, can_parse_result: bool) -> BankParser:
    parser = MagicMock(spec=BankParser)
    parser.bank_name = bank_name
    parser.can_parse.return_value = can_parse_result
    return parser


def test_get_parser_returns_matching_parser() -> None:
    matching = _make_mock_parser("TestBank", can_parse_result=True)
    factory = ParserFactory(parsers=[matching])
    result = factory.get_parser(Path("statement.pdf"))
    assert result is matching


def test_get_parser_skips_non_matching_parser() -> None:
    non_matching = _make_mock_parser("OtherBank", can_parse_result=False)
    matching = _make_mock_parser("TestBank", can_parse_result=True)
    factory = ParserFactory(parsers=[non_matching, matching])
    result = factory.get_parser(Path("statement.pdf"))
    assert result is matching


def test_get_parser_raises_when_no_parser_matches() -> None:
    factory = ParserFactory(parsers=[_make_mock_parser("Bank", can_parse_result=False)])
    with pytest.raises(UnsupportedBankError):
        factory.get_parser(Path("unknown_bank.pdf"))


def test_get_parser_raises_for_empty_parser_list() -> None:
    factory = ParserFactory(parsers=[])
    with pytest.raises(UnsupportedBankError):
        factory.get_parser(Path("any.pdf"))


def test_supported_banks_returns_registered_names() -> None:
    parsers = [_make_mock_parser("BankA", True), _make_mock_parser("BankB", True)]
    factory = ParserFactory(parsers=parsers)
    assert factory.supported_banks == ["BankA", "BankB"]
