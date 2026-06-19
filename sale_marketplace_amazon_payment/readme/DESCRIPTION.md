This module imports closed Amazon settlements (Finances API) and turns each into
a balanced GL journal entry, then reconciles the settled principal per order
against the posted customer invoice:

- **Financial events** — shipment, refund, referral/FBA/service fees,
  advertising, tax, shipping, and promotions are recorded per settlement group.
- **Journal entry** — each event type posts to its configured account; the entry
  always balances against the journal's bank/clearing account.
- **Reconciliation** — per Amazon order, the settled principal is compared to the
  invoiced total and flagged matched, variance, or no-invoice.

A scheduled action (*Amazon: Sync Settlements*, disabled by default) pulls closed
settlement groups.
