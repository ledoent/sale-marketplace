In the *Amazon Inventory (FBM)* section of the channel:

- **Inventory Sync**: enable pushing FBM quantities for this channel.
- **Fulfillment Locations**: stock locations counted toward the Amazon
  quantity. Leave empty to use the warehouse's default stock location.
- **Expose Ratio**: fraction of available stock to publish (0.0–1.0).
- **Min Reserve**: units always held back for internal orders.

Pushed quantity = `floor(free_qty * expose_ratio) - min_reserve`, clamped to 0.
