"""bank-agent-llm: Local-first AI pipeline for personal financial intelligence."""

__version__ = "0.1.0"
__all__ = ["Pipeline", "ParserFactory", "BankParser", "RawTransaction"]

from bank_agent_llm.parsers.base import BankParser, RawTransaction
from bank_agent_llm.parsers.factory import ParserFactory
from bank_agent_llm.pipeline import Pipeline
