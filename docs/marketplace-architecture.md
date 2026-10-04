# Marketplace architecture

The marketplace addons extend OCA sale-channel.

## Dependency boundaries

- `sale_marketplace` depends on `sale_channel_product`, adds a separate
  `sale.channel.product` SKU binding, and supplies `_marketplace_channel_types()`.
- `sale_marketplace_import` depends on `sale_marketplace` and `sale_import_base`;
  `_create_import_payload()` creates a queued import payload.
- `sale_marketplace_amazon` registers `channel_type = amazon` and extends the
  marketplace-type list. There is no generic `marketplace`/`ecom` selection split.
- `sale_marketplace_amazon_sale` depends on the import boundary and extends the importer
  and its schema to retain Amazon order-item identity.

These boundaries organize dependencies; they do not make the framework freely swappable.
Connectors inherit `sale.channel`, `sale.channel.product`, and the sale-channel
importer. Replacing sale-channel would require adapting those models, views, and
importer extensions as well as the two boundary modules.
