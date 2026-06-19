Orders are imported into native Odoo sale orders, tagged with their
`sale_channel_id` and a `sale.channel.partner` binding for the buyer.

- Enable the *Amazon: Import Orders* scheduled action (disabled by default) to
  poll each active Amazon channel incrementally.
- Order lines are matched to products through the channel's product (SKU)
  bindings; import the listings first (see *Sale Marketplace Amazon Listing*)
  so SKUs resolve.
- Use the channel's import settings (confirm / invoice after import, pricelist)
  inherited from *sale_import_base* to control post-import behaviour.
