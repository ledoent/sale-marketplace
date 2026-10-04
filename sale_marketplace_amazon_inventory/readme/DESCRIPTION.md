This module pushes merchant-fulfilled (FBM) stock quantities from Odoo to
Amazon listings via the SP-API.

For each active channel product binding it computes an exposable quantity from
the configured fulfilment locations — `floor(free_qty * expose_ratio) -
min_reserve` — and patches the listing's `fulfillment_availability`. A
scheduled action (*Amazon: Push Inventory*, disabled by default) pushes
changed quantities per active channel.
