This module is the boundary between marketplace connectors and the
`sale_import_base` order-ingest pipeline.

It depends on `sale_import_base` so that connector modules (Amazon, eBay, ...)
do not have to. Connectors build a `sale_import_base` SaleOrder schema dict and
call `sale.channel._create_import_payload(data)` to enqueue an import, rather
than referencing `sale.import.payload` directly.

Keeping the dependency on sale-channel's import framework in a single place
means it can be swapped or adapted later without touching every connector.
