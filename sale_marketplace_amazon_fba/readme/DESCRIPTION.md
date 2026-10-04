This module pulls Amazon FBA inventory (FBA Inventory API,
getInventorySummaries) into per-SKU records and surfaces the drift between
Amazon's fulfillable quantity and the matching Odoo product's on-hand quantity
at the channel warehouse.

A scheduled action (*Amazon: Sync FBA Inventory*, disabled by default) refreshes
the FBA inventory snapshot per channel.
