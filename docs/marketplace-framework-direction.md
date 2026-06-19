# sale-marketplace — framework direction (for Pedro)

**Status:** decision draft, not yet implemented. Working doc on branch
`18.0-add-sale_marketplace_amazon`, uncommitted — share / paste into PR #1 as needed.

## The question

`ledoent/sale-marketplace` is meant to become a **generic marketplace project** — a
common place to connect third-party marketplaces (Amazon first, then eBay / Walmart /
etc.), distinct from generic e-commerce channels (own webshop, Shopify, Woo). The Amazon
suite currently builds on OCA's **sale-channel** framework. Before locking the initial
commit we need to decide _how_ the marketplace project relates to sale-channel.

## What the Amazon suite actually uses from sale-channel

Not just the order import — three distinct ties:

| sale-channel module    | used for                                                      | how                                                                                                                                             |
| ---------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `sale_channel` (base)  | the `sale.channel` model — "a marketplace is a channel"       | `_inherit = "sale.channel"` across the suite; views inherit `sale_channel.sale_channel_view_form`; cron binds `sale_channel.model_sale_channel` |
| `sale_channel_product` | `sale.channel.product` binding (listings / inventory mapping) | `sale_marketplace` depends on it directly; `…_listing` / `…_inventory` inherit `sale.channel.product`                                           |
| `sale_import_base`     | `sale.import.payload` order-ingest pipeline                   | only `sale_marketplace_amazon_sale`                                                                                                             |

So the channels + product-bindings data model _is_ sale-channel's data model. The
order-import dependency is just one of the three.

## Options considered

1. **Be a sale-channel extension** (today's de-facto state). Lowest effort, rides OCA,
   but permanently welded to sale-channel's modeling and to akretion's in-flight
   `sale_import_base` migration.
2. **Own marketplace framework** (`marketplace.*` models, no sale-channel). Full
   control + cleanest "generic marketplace" story, but reimplements and maintains what
   sale-channel already does, and diverges from OCA (hurts upstreamability).
3. **Thin abstraction over sale-channel** ← **chosen.** Keep sale-channel underneath,
   but make `sale_marketplace` the boundary that owns the sale-channel dependency, so
   it's an implementation detail we could swap later. Lets the first commit be clean +
   generic without permanently welding to, or forking, the framework.

## Decision

**Option 3**, with a `marketplace` vs `ecom` split:

- `sale.channel.channel_type = 'ecom'` → webshop / Shopify / Woo / own site → plain
  sale-channel, untouched.
- `sale.channel.channel_type = 'marketplace'` → Amazon / eBay / Walmart → the
  marketplace layer lights up (listings, FBA/MCF inventory, fees, settlement, order
  import). Marketplace behavior is **gated to marketplace channels**.

### What "option 3" means in practical Odoo terms

Odoo has no interface/hiding: `_inherit = "sale.channel"` inherently names sale-channel,
and connectors must do it to add fields. So option 3 is **not** renaming models to
`marketplace.*` (that's option 2). It is three lighter moves:

1. **Dependency isolation.** Only `sale_marketplace` (the boundary) lists
   `sale_channel*` / `sale_import_base` in `depends`. Every connector (`…_amazon*`)
   depends on `sale_marketplace`, never on sale-channel directly. Swap the framework
   later → touch one module.
2. **`channel_type` discriminator** on `sale.channel`, defined in `sale_marketplace`,
   gating marketplace-only logic.
3. **Marketplace mixin / interface** in `sale_marketplace` that connectors target,
   instead of reaching into sale-channel internals.

## Concrete deltas (small — not a rewrite)

Dependency routing is already correct everywhere except one leak:

- **One real leak:** `sale_marketplace_amazon_sale` depends on `sale_import_base`
  **directly**. Fix: pull `sale_import_base` into the `sale_marketplace` boundary (or a
  dedicated `sale_marketplace_import` sub-module); `…_amazon_sale` then depends on that.
- **Add** `channel_type` selection + marketplace gating to `sale_marketplace`.
- **Add** the marketplace mixin/interface to `sale_marketplace`.
- The pervasive `_inherit = "sale.channel"` in connectors is fine — expected field
  extension, not a dependency leak. No model renames.

## Open questions for Pedro

1. Boundary shape: extend `channel_type` onto `sale.channel` directly, or carry
   marketplace semantics on a thin mixin so the discriminator isn't a sale-channel
   concern?
2. Import pipeline: keep `sale_import_base` as the order-ingest contract behind the
   boundary, or define a marketplace-owned import interface that _adapts_ to
   `sale_import_base` today (cleaner swap story, more code)?
3. Naming for upstream: does this live under OCA `sale-marketplace` as a sale-channel
   companion, and is the `ecom` vs `marketplace` discriminator something sale-channel
   itself should host (so generic channels and marketplaces share one typed model)?
