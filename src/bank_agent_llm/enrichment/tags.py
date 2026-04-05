"""Tag taxonomy — loads and validates the canonical tag vocabulary.

Tags are defined in enrichment/data/tags.yaml. The taxonomy is a two-level
hierarchy: parent tags (for charts) and leaf/child tags (for filtering).

Usage:
    from bank_agent_llm.enrichment.tags import get_taxonomy
    tx = get_taxonomy()
    tx.parent_of("restaurante")  # → "comida"
    tx.is_expense("pago-tarjeta") # → False
    tx.all_ids()                  # → ["comida", "restaurante", ...]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class Tag:
    id: str
    display: str
    color: str
    icon: str
    is_expense: bool
    parent_id: str | None = None
    children: tuple[str, ...] = field(default_factory=tuple)


class TagTaxonomy:
    """In-memory representation of the tag hierarchy."""

    def __init__(self, tags: list[Tag]) -> None:
        self._by_id: dict[str, Tag] = {t.id: t for t in tags}

    # ── Lookups ───────────────────────────────────────────────────────────────

    def get(self, tag_id: str) -> Tag | None:
        return self._by_id.get(tag_id)

    def all_ids(self) -> list[str]:
        return list(self._by_id.keys())

    def parent_ids(self) -> list[str]:
        """Top-level tags only (no parent)."""
        return [t.id for t in self._by_id.values() if t.parent_id is None]

    def parent_of(self, tag_id: str) -> str | None:
        tag = self._by_id.get(tag_id)
        return tag.parent_id if tag else None

    def is_expense(self, tag_id: str) -> bool:
        tag = self._by_id.get(tag_id)
        if tag is None:
            return True  # unknown tags treated as expenses
        if tag.parent_id:
            parent = self._by_id.get(tag.parent_id)
            return parent.is_expense if parent else True
        return tag.is_expense

    def primary_tag(self, tags: list[str]) -> str | None:
        """Return the most-specific expense tag from a list, for chart grouping.

        Prefers leaf tags over parent tags. Falls back to first non-expense tag
        if no expense tag found. Returns None for empty list.
        """
        if not tags:
            return None
        # Prefer leaf expense tags
        for tag_id in tags:
            tag = self._by_id.get(tag_id)
            if tag and tag.parent_id and self.is_expense(tag_id):
                return tag_id
        # Fall back to any tag in the list
        return tags[0]

    def validate(self, tags: list[str]) -> list[str]:
        """Return only tag IDs present in the taxonomy, warn on unknowns."""
        return [t for t in tags if t in self._by_id]

    def display_name(self, tag_id: str) -> str:
        tag = self._by_id.get(tag_id)
        return tag.display if tag else tag_id


def _load_taxonomy(path: Path) -> TagTaxonomy:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    tags: list[Tag] = []
    for entry in data.get("tags", []):
        parent_id = entry["id"]
        children_ids: list[str] = []

        for child in entry.get("children", []):
            child_tag = Tag(
                id=child["id"],
                display=child["display"],
                color=entry.get("color", "#94A3B8"),
                icon=entry.get("icon", "•"),
                is_expense=entry.get("is_expense", True),
                parent_id=parent_id,
            )
            tags.append(child_tag)
            children_ids.append(child["id"])

        parent_tag = Tag(
            id=parent_id,
            display=entry["display"],
            color=entry.get("color", "#94A3B8"),
            icon=entry.get("icon", "•"),
            is_expense=entry.get("is_expense", True),
            children=tuple(children_ids),
        )
        tags.append(parent_tag)

    return TagTaxonomy(tags)


@lru_cache(maxsize=1)
def get_taxonomy() -> TagTaxonomy:
    """Return the singleton tag taxonomy loaded from data/tags.yaml."""
    return _load_taxonomy(_DATA_DIR / "tags.yaml")
