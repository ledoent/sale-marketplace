This module adds Amazon pricing to marketplace channel product (SKU) bindings:

- **Price push** — push a target price to Amazon via the Listings Items API,
  driven by the channel's pricing mode (pricelist, competitive, or manual).
- **Competitive pricing** — pull buy-box prices via the Product Pricing API and
  record whether you currently win the buy box per listing.
- **Competitive rules** — match the buy box, undercut it by a percentage, or
  price at cost plus a target margin; every rule is clamped to a cost-plus-margin
  floor so a push never drops below your floor.
- **Price history** — an audit trail of every price change with its trigger and
  the rule that produced it.

A scheduled action (*Amazon: Sync Prices*, disabled by default) syncs competitive
prices and pushes for channels with price push enabled.
