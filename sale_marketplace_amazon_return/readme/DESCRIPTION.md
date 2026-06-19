This module ingests Amazon merchant-fulfilled (MFN) returns via the Reports API
(GET_XML_RETURNS_DATA_BY_RETURN_DATE) and optionally automates the follow-up:

- Request and fetch the returns report, parse RMAs and their line items, and
  upsert return records (idempotent per RMA).
- Optionally create a restock picking (customer → stock) and a credit note from
  the original invoice.

Quality guardrails: a missing return quantity defaults to 0 (never silently
restocks one unit), XML parse failures are surfaced on the report record rather
than swallowed, and the return state is always derived from what was actually
created (picking / credit note), so partial automation never leaves a misleading
state.

A scheduled action (*Amazon: Sync Returns*, disabled by default) pulls returns.
