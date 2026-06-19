On an Amazon channel, click *Import Listings* to pull the seller's active
listings from Amazon and create or update the channel product (SKU) bindings,
storing each listing's ASIN. A *Seller ID* must be set on the channel.

The resulting `sale.channel.product` bindings are what the order-import and
inventory-push modules use to map between Amazon SKUs and Odoo products.
