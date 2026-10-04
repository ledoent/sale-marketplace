This module turns a `sale.channel` into an **Amazon Selling Partner API**
marketplace channel. It registers the `amazon` channel type and adds the
SP-API connection configuration (LWA credentials, marketplace, seller id,
fulfilment warehouse, sandbox toggle) plus a *Test Connection* action.

It only provides the channel + client wiring. Order import, listings,
inventory and tracking are provided by the `sale_marketplace_amazon_*`
modules built on top.
