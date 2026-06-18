This module is the generic base for marketplace connectors built on
`sale_channel`. It adds the per-channel **product/SKU binding** that
`sale_channel` lacks: a `sale.channel.product` model mapping an external
listing identifier (an Amazon seller SKU, an eBay listing id, ...) to an Odoo
product for a given channel — the product-side counterpart of the existing
`sale.channel.partner` binding.

It also flags which channel types are marketplaces (`is_marketplace`), so
generic code can target marketplace channels. Marketplace-specific modules
(`sale_marketplace_amazon*`, ...) build on top of it.
