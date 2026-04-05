"""Tests for ParserFactory."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bank_agent_llm.parsers.base import BankParser
from bank_agent_llm.parsers.factory import ParserFactory, UnsupportedBankError


def _make_mock_parser(bank_name: str, can_parse_result: bool) -> BankParser:
    parser = MagicMock(spec=BankParser)
    parser.bank_name = bank_name
    parser.can_parse.return_value = can_parse_result
    return parser


@patch("bank_agent_llm.parsers.factory._extract_pdf_hint", return_value="BANK HEADER TEXT")
def test_get_parser_returns_matching_parser(mock_hint: MagicMock) -> None:
    matching = _make_mock_parser("TestBank", can_parse_result=True)
    factory = ParserFactory(parsers=[matching])
    result = factory.get_parser(Path("statement.pdf"))
    assert result is matching
    matching.can_parse.assert_called_once_with(Path("statement.pdf"), hint="BANK HEADER TEXT")


@patch("bank_agent_llm.parsers.factory._extract_pdf_hint", return_value="")
def test_get_parser_skips_non_matching_parser(mock_hint: MagicMock) -> None:
    non_matching = _make_mock_parser("OtherBank", can_parse_result=False)
    matching = _make_mock_parser("TestBank", can_parse_result=True)
    factory = ParserFactory(parsers=[non_matching, matching])
    result = factory.get_parser(Path("statement.pdf"))
    assert result is matching


@patch("bank_agent_llm.parsers.factory._extract_pdf_hint", return_value="")
def test_get_parser_raises_when_no_parser_matches(mock_hint: MagicMock) -> None:
    factory = ParserFactory(parsers=[_make_mock_parser("Bank", can_parse_result=False)])
    with pytest.raises(UnsupportedBankError):
        factory.get_parser(Path("unknown_bank.pdf"))


@patch("bank_agent_llm.parsers.factory._extract_pdf_hint", return_value="")
def test_get_parser_raises_for_empty_parser_list(mock_hint: MagicMock) -> None:
    factory = ParserFactory(parsers=[])
    with pytest.raises(UnsupportedBankError):
        factory.get_parser(Path("any.pdf"))


def test_supported_banks_returns_registered_names() -> None:
    parsers = [_make_mock_parser("BankA", True), _make_mock_parser("BankB", True)]
    factory = ParserFactory(parsers=parsers)
    assert factory.supported_banks == ["BankA", "BankB"]


@patch("bank_agent_llm.parsers.factory._extract_pdf_hint", return_value="")
def test_hint_extracted_once_for_multiple_parsers(mock_hint: MagicMock) -> None:
    parsers = [_make_mock_parser(f"Bank{i}", False) for i in range(5)]
    parsers[-1].can_parse.return_value = True
    factory = ParserFactory(parsers=parsers)
    factory.get_parser(Path("statement.pdf"))
    mock_hint.assert_called_once()
