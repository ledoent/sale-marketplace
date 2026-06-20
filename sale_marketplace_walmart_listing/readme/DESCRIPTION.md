Import Walmart Marketplace items into `sale.channel.product` (SKU) bindings.

The **Import Listings** action on a Walmart channel pulls items from the Walmart
Items API and upserts one channel-product binding per SKU, matching Odoo products
by internal reference (`default_code`) and storing the Walmart Product ID
(`wpid`). These bindings are what the order, inventory and pricing modules use to
map between Walmart SKUs and Odoo products.
