"""TransactionEnricher — orchestrates all tagging layers.

Layer execution order:
  1. DirectionRules: credits → pago-tarjeta / transferencia / ingreso
  2. SignatureRules: keyword matching from YAML rules (~75-80% of debits)
  3. MerchantCache:  reuse a prior Ollama result for the same description
  4. OllamaClient:   batch LLM call for remaining untagged transactions

Transactions with tag_source='manual' are never re-tagged.

Usage:
    enricher = TransactionEnricher(settings)
    result = enricher.enrich(session, force=False)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from bank_agent_llm.config import Settings
from bank_agent_llm.enrichment.ollama import OllamaClient
from bank_agent_llm.enrichment.rules import SignatureRules, TagAssignment
from bank_agent_llm.storage.models import Transaction

logger = logging.getLogger(__name__)


@dataclass
class EnrichResult:
    total: int = 0
    by_rules: int = 0
    by_cache: int = 0
    by_llm: int = 0
    skipped_manual: int = 0
    already_tagged: int = 0
    pending: int = 0       # untagged because LLM unavailable
    errors: int = 0
    llm_unavailable: bool = False

    @property
    def tagged(self) -> int:
        return self.by_rules + self.by_cache + self.by_llm


class TransactionEnricher:
    """Applies multi-layer tagging to transactions stored in the DB."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._rules = SignatureRules()
        self._ollama = OllamaClient(
            base_url=settings.ollama.base_url,
            model=settings.ollama.categorization_model,
        )

    # ── Public ────────────────────────────────────────────────────────────────

    def enrich(self, session: Session, *, force: bool = False) -> EnrichResult:
        """Tag all pending transactions in the given session.

        Args:
            session: Active SQLAlchemy session.
            force: If True, re-tag even previously tagged transactions
                   (except manual ones).
        """
        from bank_agent_llm.storage.repository import EnrichmentRepository

        repo = EnrichmentRepository(session)
        transactions = repo.pending_transactions(include_tagged=force)

        result = EnrichResult(total=len(transactions))
        logger.info("Enriching %d transaction(s) (force=%s)", len(transactions), force)

        to_llm: list[Transaction] = []

        for tx in transactions:
            if tx.tag_source == "manual":
                result.skipped_manual += 1
                continue

            if tx.tag_source not in ("pending", "") and not force:
                result.already_tagged += 1
                continue

            assignment = self._apply_rules(tx, repo)

            if assignment:
                self._save(tx, assignment, repo)
                result.by_rules += 1
            else:
                to_llm.append(tx)

        # Batch LLM call for unmatched transactions
        if to_llm:
            llm_results = self._run_llm(to_llm, repo, result)
            for tx in to_llm:
                assignment = llm_results.get(tx.id)
                if assignment:
                    self._save(tx, assignment, repo)
                else:
                    result.pending += 1

        session.flush()
        logger.info(
            "Enrichment done — rules=%d cache=%d llm=%d pending=%d",
            result.by_rules, result.by_cache, result.by_llm, result.pending,
        )
        return result

    # ── Internal ──────────────────────────────────────────────────────────────

    def _apply_rules(
        self,
        tx: Transaction,
        repo: "EnrichmentRepository",  # type: ignore[name-defined]
    ) -> TagAssignment | None:
        """Try direction rules, then keyword rules, then merchant cache."""
        # 1. Direction rules for credits
        if tx.direction == "credit":
            assignment = self._rules.match(tx.raw_description, tx.direction)
            if assignment:
                return assignment
            return self._rules.credit_fallback(tx.raw_description)

        # 2. Keyword rules for debits
        assignment = self._rules.match(tx.raw_description, tx.direction)
        if assignment:
            return assignment

        # 3. Merchant cache (previous LLM result for same description)
        cached = repo.get_merchant_cache(_merchant_key(tx.raw_description))
        if cached:
            return TagAssignment(
                tags=cached.tags,
                merchant_name=cached.merchant_name,
                source="llm_cache",
            )

        return None

    def _run_llm(
        self,
        transactions: list[Transaction],
        repo: "EnrichmentRepository",  # type: ignore[name-defined]
        result: EnrichResult,
    ) -> dict[int, TagAssignment]:
        if not self._ollama.is_available():
            result.llm_unavailable = True
            logger.warning(
                "Ollama unavailable — %d transaction(s) left as 'pending'. "
                "Run 'bank-agent enrich' after starting Ollama.",
                len(transactions),
            )
            return {}

        inputs = [
            (tx.id, tx.raw_description, float(tx.amount), tx.direction)
            for tx in transactions
        ]
        try:
            llm_results = self._ollama.tag_batch(inputs)
        except Exception as exc:  # noqa: BLE001
            logger.error("Ollama batch call failed: %s", exc)
            result.errors += 1
            return {}

        # Cache results so the same merchant isn't sent to Ollama again
        for tx in transactions:
            assignment = llm_results.get(tx.id)
            if assignment:
                key = _merchant_key(tx.raw_description)
                repo.upsert_merchant_cache(key, assignment.tags, assignment.merchant_name, "llm")
                result.by_llm += 1

        return llm_results

    @staticmethod
    def _save(
        tx: Transaction,
        assignment: TagAssignment,
        repo: "EnrichmentRepository",  # type: ignore[name-defined]
    ) -> None:
        repo.save_tags(
            transaction_id=tx.id,
            tags=assignment.tags,
            merchant_name=assignment.merchant_name,
            source=assignment.source,
        )


def _merchant_key(raw_description: str) -> str:
    """Normalize a raw_description into a stable cache key."""
    return raw_description.upper().strip()[:100]
