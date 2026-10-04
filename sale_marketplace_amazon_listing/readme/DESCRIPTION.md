This module imports a seller's Amazon listings into `sale.channel.product`
(SKU) bindings, and adds the Amazon `asin` to those bindings.

It pulls the SP-API Listings Items for an Amazon channel and maps each seller
SKU to an Odoo product (by internal reference), creating or updating the
channel binding. These bindings are what the order-import and inventory-push
modules use to resolve products.
