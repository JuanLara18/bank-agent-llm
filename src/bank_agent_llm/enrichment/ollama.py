"""Ollama HTTP client for batch transaction tagging.

Sends up to BATCH_SIZE transactions per request using the Ollama /api/generate
endpoint. Requests a JSON response from the model with a strict prompt that
enumerates the canonical tag vocabulary.

Usage:
    client = OllamaClient(base_url="http://localhost:11434", model="mistral:7b")
    assignments = client.tag_batch(transactions)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from bank_agent_llm.enrichment.rules import TagAssignment
from bank_agent_llm.enrichment.tags import get_taxonomy

logger = logging.getLogger(__name__)

BATCH_SIZE = 5
_TIMEOUT = 120.0  # seconds per batch call


@dataclass
class _TxInput:
    id: int
    desc: str
    amount: float
    direction: str


class OllamaClient:
    """Categorizes transactions in batches using a local Ollama model."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._taxonomy = get_taxonomy()

    # ── Public ────────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if Ollama is running and the configured model is available."""
        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=5.0)
            if resp.status_code != 200:
                return False
            models = [m.get("name", "").split(":")[0] for m in resp.json().get("models", [])]
            model_name = self._model.split(":")[0]
            available = model_name in models
            if not available:
                logger.warning(
                    "Ollama model '%s' not found. Available: %s. "
                    "Run: ollama pull %s",
                    self._model, models, self._model,
                )
            return available
        except Exception:  # noqa: BLE001
            logger.warning("Ollama not reachable at %s", self._base_url)
            return False

    def tag_batch(
        self, tx_inputs: list[tuple[int, str, float, str]]
    ) -> dict[int, TagAssignment]:
        """Tag a list of (id, description, amount, direction) tuples.

        Returns a dict mapping transaction id → TagAssignment.
        Processes in batches of BATCH_SIZE. Unknown/failed IDs are omitted.
        """
        results: dict[int, TagAssignment] = {}
        items = [_TxInput(id=i, desc=d, amount=a, direction=dr)
                 for i, d, a, dr in tx_inputs]

        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start : start + BATCH_SIZE]
            batch_results = self._call_batch(batch)
            results.update(batch_results)

        return results

    # ── Internal ──────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_batch(self, batch: list[_TxInput]) -> dict[int, TagAssignment]:
        prompt = self._build_prompt(batch)
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 1024},
        }

        try:
            resp = httpx.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Ollama HTTP error: %s", exc)
            return {}

        raw = resp.json().get("response", "")
        return self._parse_response(raw, batch)

    def _build_prompt(self, batch: list[_TxInput]) -> str:
        tag_list = ", ".join(self._taxonomy.all_ids())
        tx_lines = "\n".join(
            f'{i+1}. id={tx.id} | {tx.direction} | ${tx.amount:,.0f} | {tx.desc}'
            for i, tx in enumerate(batch)
        )
        example_id = batch[0].id
        return f"""Categorize Colombian credit card transactions. Use ONLY these tags: {tag_list}

Rules:
- 1-3 tags per transaction, leaf tag first (e.g. "restaurante" before "comida").
- credit direction → pago-tarjeta (if payment) or ingreso (if salary/transfer in).
- INTERESES/MORA → intereses, banco. GMF/GRAVAMEN → impuesto-gmf, banco.
- CUOTA DE MANEJO → cuota-manejo, banco. AMPLIACION → comisiones, banco.
- merchant: short human-readable name, Title Case. Use brand name if known.

Transactions:
{tx_lines}

You MUST respond with a JSON object with key "results" containing an array.
Each element: {{"id": <number>, "tags": ["tag1", "tag2"], "merchant": "Name"}}

Example: {{"results": [{{"id": {example_id}, "tags": ["comida", "restaurante"], "merchant": "McDonald's"}}]}}"""

    def _parse_response(
        self, raw: str, batch: list[_TxInput]
    ) -> dict[int, TagAssignment]:
        raw = raw.strip()

        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        # Parse JSON — tolerate both array and object wrappers
        items: list[dict[str, Any]] = []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                items = parsed
            elif isinstance(parsed, dict):
                # {"results": [...]} or {"transactions": [...]}
                for v in parsed.values():
                    if isinstance(v, list):
                        items = v
                        break
                if not items:
                    # {"323": {"tags": [...], "merchant": "..."}, ...}
                    batch_ids_str = {str(tx.id) for tx in batch}
                    for k, v in parsed.items():
                        if k in batch_ids_str and isinstance(v, dict):
                            v["id"] = int(k)
                            items.append(v)
        except json.JSONDecodeError:
            # Last resort: extract individual objects with regex
            import re
            for m in re.finditer(r'\{[^{}]+\}', raw):
                try:
                    obj = json.loads(m.group())
                    if "id" in obj:
                        items.append(obj)
                except json.JSONDecodeError:
                    pass
            if not items:
                logger.warning(
                    "Ollama: unparseable response for batch of %d tx: %.150s",
                    len(batch), raw,
                )
                return {}

        batch_ids = {tx.id for tx in batch}
        results: dict[int, TagAssignment] = {}

        for item in items:
            tx_id = item.get("id")
            if not isinstance(tx_id, int):
                try:
                    tx_id = int(tx_id)
                except (TypeError, ValueError):
                    continue
            if tx_id not in batch_ids:
                continue
            raw_tags = item.get("tags", [])
            if isinstance(raw_tags, str):
                raw_tags = [t.strip() for t in raw_tags.replace(",", " ").split()]
            valid_tags = self._taxonomy.validate(raw_tags)
            if not valid_tags:
                logger.debug("No valid tags for tx %s: %s", tx_id, raw_tags)
                continue
            results[tx_id] = TagAssignment(
                tags=valid_tags,
                merchant_name=str(item.get("merchant", "")).strip() or valid_tags[0],
                source="llm",
            )

        return results
