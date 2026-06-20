Ingest Walmart Marketplace returns and automate restock pickings and credit
notes.

A cron pulls return orders per channel from the Walmart Returns API, upserts each
return (idempotent per return order) with its lines mapped to Odoo products by
SKU, and optionally creates a restock picking (customer -> stock) and a customer
credit note matched against the order's posted invoices. The return state always
reflects what was actually created (new / restock created / credited / done), and
the sync cursor only advances when a pull parses cleanly so returns are never
skipped on a transient failure.
