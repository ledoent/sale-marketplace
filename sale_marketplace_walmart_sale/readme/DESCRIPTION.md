Import Walmart Marketplace orders into Odoo as native sale orders, and keep the
marketplace order in sync over its lifecycle.

- **Order import**: a cron polls the Walmart Orders API per active Walmart
  channel and enqueues one queue job per order. Each order is mapped to the
  `sale_import_base` schema and run through the marketplace import boundary
  (`sale_marketplace_import`), which creates the sale order, the customer partner
  and the `sale.channel.partner` binding. Line SKUs are resolved through
  `sale.channel.product` bindings, and the channel warehouse is applied.
- **Order acknowledgement**: Walmart auto-cancels orders that are not
  acknowledged within its SLA, so imported orders are acknowledged back to
  Walmart (auto via a cron, or manually from the order). Tracked on the order.
- **Cancellation push**: cancelling a Walmart order in Odoo pushes the
  cancellation back to Walmart so the marketplace order is cancelled too.
- **Marketplace-facilitator tax**: Walmart collects and remits the buyer's sales
  tax, so a configurable fiscal position maps the product's customer taxes away
  on import (no double-counting), while the tax Walmart collected is captured on
  the order for reporting.
