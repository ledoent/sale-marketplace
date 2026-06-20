Push prices from Odoo to Walmart Marketplace listings.

The target price for each binding comes from the channel's pricing mode (manual
or a pricelist) and is clamped to a **margin-on-revenue floor**: the price at
which `(price - cost) / price` equals the configured floor margin, so a listing
never sells below its target net margin. Only changed prices are pushed, every
change is recorded in a per-binding price-history audit trail, and per-binding
errors are isolated. A cron and a manual **Push Prices** action are provided,
both running as queue jobs.
