# Known gaps

Files and features that the current codebase does not handle, tracked here so
that future changes can decide whether to close the gap or leave it alone.

## Parser gaps

### Old Bancolombia card format (Feb–Aug 2025, 14 PDFs)

**Affected files:** `Extracto_*_2025{02,03,04,05,06,07,08}_TARJETA_VISA_2158.pdf`
and `..._TARJETA_MASTERCARD_0542.pdf` — the card numbers that were later
reissued as `_1332` / `_6745`.

**Symptom:** `BancolombiaParser.can_parse()` returns `False` because the
signature string `NIT: 890.903.938-8` is not present anywhere in the PDF
(not only on page 1). Even if detection were relaxed, `_parse_row` returns
zero transactions against this layout — the token grammar is different.

**Why deferred:** These statements predate the format the current parser was
built for. Recovering them would require:
1. A separate detection signature (possibly filename-based, but the factory
   is hint-driven today).
2. A second `_parse_row` grammar behind a layout switch.
3. New fixtures and tests.

None of it unblocks a milestone; the newer `_1332` / `_6745` statements
(Sep 2025 onward) parse cleanly, and monthly tracking is complete from
September 2025 forward.

**How to pick this back up:**
- Add a `BancolombiaCardLegacyParser` in `parsers/bancolombia_card_legacy.py`
  rather than branching inside `BancolombiaParser`.
- Register it in `parsers/factory.py` *after* the current Bancolombia parsers.
- Anonymize one sample PDF into `tests/fixtures/` and cover both layouts.

### Bancolombia `COMISIONES_CONSOLIDADAS` (1 PDF)

**Affected file:** `Extracto_1049973191_202512_COMISIONES_CONSOLIDADAS_6157.pdf`.

**Symptom:** The card parser matches by signature but `parse()` returns zero
rows. This statement is a fee roll-up with a different row layout.

**Why deferred:** Single file, purely informational. Fees are already
reflected in the underlying card statements.

## Schema gaps

See `docs/architecture.md` for the current schema. Dead columns that survive
from early M1 scaffolding (`transactions.category_id`, `category_confidence`,
`normalized_description`, `transaction_time`, plus the `categories` table)
are targeted for removal in a future `refactor/drop-dead-schema` branch.
They are never written by the current enricher — `tags` + `tag_source` +
`merchant_name` are the canonical enrichment fields.
