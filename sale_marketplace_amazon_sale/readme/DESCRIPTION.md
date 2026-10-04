This module imports Amazon orders into Odoo as native sale orders.

It polls the SP-API Orders API for an Amazon `sale.channel`, and feeds each
order through the `sale_import_base` importer pipeline. The result is a native
`sale.order` tagged with its `sale_channel_id`, a `sale.channel.partner`
binding for the buyer, and order lines whose products are resolved through the
channel's `sale.channel.product` (SKU) bindings.

A scheduled action (*Amazon: Import Orders*, disabled by default) enqueues an
incremental import per active Amazon channel.
