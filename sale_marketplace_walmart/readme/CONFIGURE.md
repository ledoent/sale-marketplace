The Walmart suite is split into one base module and per-feature modules; install
only what you need on top of `sale_marketplace_walmart`:

- `sale_marketplace_walmart` — channel + API client (this module)
- `sale_marketplace_walmart_sale` — order import, acknowledgement, cancellation, tax
- `sale_marketplace_walmart_listing` — item import + export (feeds)
- `sale_marketplace_walmart_inventory` — stock push
- `sale_marketplace_walmart_pricing` — price push
- `sale_marketplace_walmart_stock` — tracking push
- `sale_marketplace_walmart_payment` — settlement → GL + reconciliation
- `sale_marketplace_walmart_return` — returns → restock / credit note / refund
- `sale_marketplace_walmart_dashboard` — KPI dashboard

## Channel setup

1. Create a Sale Channel with **Channel Type = Walmart**.
2. Fill **Walmart Client ID / Secret** (sandbox or production keys from the
   Walmart Developer Portal), pick the **Walmart Market** (US/CA/MX), set
   **Sandbox Mode** while testing, and select a **Warehouse**.
3. Use **Test Connection** to verify the OAuth2 credentials.

## Per-feature configuration

- **Orders** (`_sale`): set an import look-back and a **Walmart Fiscal Position**
  that maps the product's customer taxes to 0% (Walmart remits the tax as a
  marketplace facilitator). Auto-acknowledge / auto-cancel toggles default on.
- **Inventory** (`_inventory`): enable Inventory Sync, set the expose ratio,
  minimum reserve and fulfillment locations.
- **Pricing** (`_pricing`): choose manual or pricelist mode and a margin floor.
- **Payment** (`_payment`): set the settlement journal and the income / fee /
  tax / shipping accounts used to book and reconcile settlements.
- **Returns** (`_return`): enable returns and, optionally, auto restock picking,
  auto credit note and auto refund.

The scheduled actions for each feature ship **inactive**; activate the ones you
use under Settings → Technical → Scheduled Actions.
