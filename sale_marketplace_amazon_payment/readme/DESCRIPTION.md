This module imports closed Amazon settlements (Finances API) and turns each into
a balanced **draft** GL journal entry, then compares the settled principal per order
against the posted customer invoice:

- **Financial events** — shipment, refund, referral/FBA/service fees,
  advertising, tax, shipping, and promotions are recorded per settlement group.
- **Journal entry** — each event type maps to its configured account; the draft
  balances against the journal's bank/clearing account. Nothing is auto-posted.
- **Comparison** — per Amazon order, the settled principal is compared to the
  invoiced total and flagged matched, variance, or no-invoice.

A scheduled action (*Amazon: Sync Settlements*, disabled by default) pulls closed
settlement groups.

Each poll rescans the preceding 179 days because Amazon filters groups by opening
date, not closure date. Older history requires a separate backfill. Failed groups
raise an error rather than marking the sync successful.

This is an experimental accounting aid, not receivable reconciliation. It compares
against the first posted customer invoice and does not reconcile account move lines.
An accountant must review account mappings, event completeness, and the draft before
posting, especially where sale invoices already recognize revenue. Foreign-currency
settlement entries are rejected rather than booked at an implicit 1:1 exchange rate.
