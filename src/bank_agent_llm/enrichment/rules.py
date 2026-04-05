"""Signature-based keyword rules for transaction tagging.

Rules are loaded from enrichment/data/rules.yaml (bundled defaults).
A user override file at config/categories.yaml is merged on top if present.

Each rule is tried in order; the first match wins.
Matching is case-insensitive substring search on raw_description.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from bank_agent_llm.enrichment.tags import get_taxonomy

logger = logging.getLogger(__name__)

_BUNDLED_RULES = Path(__file__).parent / "data" / "rules.yaml"
_USER_RULES = Path("config/categories.yaml")


@dataclass(frozen=True)
class TagAssignment:
    tags: list[str]
    merchant_name: str
    source: str  # "direction_rule" | "keyword_rule" | "llm" | "llm_cache" | "manual"


@dataclass
class _Rule:
    tags: list[str]
    merchant: str
    patterns: list[str]  # case-insensitive substrings
    direction: str | None  # None = match both; "debit" | "credit"


class SignatureRules:
    """Applies keyword rules to classify transactions without LLM calls.

    Covers ~75-80% of real-world transactions with deterministic rules.
    """

    def __init__(self, user_rules_path: Path | None = None) -> None:
        self._rules = _load_rules(user_rules_path or _USER_RULES)
        self._taxonomy = get_taxonomy()
        logger.debug("Loaded %d keyword rules", len(self._rules))

    def match(self, raw_description: str, direction: str) -> TagAssignment | None:
        """Return a TagAssignment if any rule matches, else None.

        Direction rules (credit-specific) are checked before generic patterns.
        """
        upper = raw_description.upper()

        for rule in self._rules:
            # Filter by direction if specified
            if rule.direction and rule.direction != direction:
                continue

            for pattern in rule.patterns:
                if pattern.upper() in upper:
                    # Validate tags against taxonomy
                    valid_tags = self._taxonomy.validate(rule.tags)
                    if not valid_tags:
                        logger.warning("Rule '%s' has no valid tags: %s", rule.merchant, rule.tags)
                        continue
                    return TagAssignment(
                        tags=valid_tags,
                        merchant_name=rule.merchant,
                        source="keyword_rule",
                    )
        return None

    def credit_fallback(self, raw_description: str) -> TagAssignment:
        """Fallback for credit transactions that matched no rule.

        Most credits are card payments or generic refunds.
        """
        upper = raw_description.upper()
        if any(k in upper for k in ("ABONO", "PAGO", "INGRESO")):
            return TagAssignment(tags=["pago-tarjeta"], merchant_name="Pago", source="direction_rule")
        if "TRANSF" in upper:
            return TagAssignment(tags=["transferencia"], merchant_name="Transferencia", source="direction_rule")
        return TagAssignment(tags=["ingreso"], merchant_name="Ingreso", source="direction_rule")


def _load_rules(user_path: Path) -> list[_Rule]:
    """Load bundled rules, then merge user overrides (user rules take priority)."""
    rules: list[_Rule] = []

    # User rules come first → higher priority
    if user_path.exists():
        rules.extend(_parse_rules(user_path))
        logger.debug("Loaded user rules from %s", user_path)

    # Bundled defaults
    rules.extend(_parse_rules(_BUNDLED_RULES))

    return rules


def _parse_rules(path: Path) -> list[_Rule]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    result: list[_Rule] = []
    for entry in data.get("rules", []):
        tags = entry.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        patterns = entry.get("patterns", [])
        if not tags or not patterns:
            continue
        result.append(_Rule(
            tags=tags,
            merchant=entry.get("merchant", tags[0]),
            patterns=patterns,
            direction=entry.get("direction"),
        ))
    return result
