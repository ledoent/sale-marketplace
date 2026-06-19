This module fulfills non-Amazon orders from Amazon FBA stock via Multi-Channel
Fulfillment (FulfillmentOutbound API):

- From a delivery, build a draft fulfillment order whose lines are matched to
  Amazon seller SKUs through the channel's FBA inventory (duplicate SKUs are
  aggregated).
- Submit it (createFulfillmentOrder), poll its status (getFulfillmentOrder), and
  cancel it (cancelFulfillmentOrder).
- Tracking numbers from all shipments and packages are collected back onto the
  fulfillment order and the first is written to the delivery.

A scheduled action (*Amazon: Sync MCF Status*, disabled by default) refreshes the
status of open fulfillment orders, isolating per-order failures.
