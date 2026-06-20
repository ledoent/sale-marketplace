Push available stock quantities from Odoo to Walmart Marketplace listings.

For each active Walmart channel-product binding with inventory sync enabled, the
exposed quantity is computed as `max(0, floor(free_qty * expose_ratio) -
min_reserve)` over the configured fulfillment locations (or the channel
warehouse's stock location), and pushed to the Walmart Inventory API. Only
changed quantities are pushed. A cron and a manual **Push Inventory** action are
provided; pushes run as queue jobs.
