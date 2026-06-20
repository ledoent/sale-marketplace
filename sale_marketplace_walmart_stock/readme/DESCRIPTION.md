Push carrier tracking numbers from Odoo deliveries to Walmart Marketplace.

When an outgoing delivery linked to a Walmart sale order is validated and carries
a tracking reference, a queue job marks each order line Shipped on Walmart via
the Orders shipping API, including the carrier, tracking number and ship date.
Carrier display names are mapped to Walmart carrier codes (unknown carriers are
sent via `otherCarrier`). A manual **Push Tracking to Walmart** button on the
picking re-pushes on demand.
