This is the base module for the Walmart Marketplace connector suite. It adds a
`walmart` channel type to `sale.channel` and a thin Walmart Marketplace REST API
client (OAuth2 client-credentials token + signed requests), plus a Test
Connection action.

It is built on the sale-channel framework + the marketplace boundary (the same
option-3 architecture as the Amazon suite): only `sale_marketplace` /
`sale_marketplace_import` ever name a sale-channel module. Feature modules
(orders, listings, inventory, pricing, tracking, settlement, returns) build on
top of this base.
