This module estimates Amazon selling fees per channel product (SKU) binding via
the Product Fees API (GetMyFeesEstimate) and turns them into a fee-aware margin:

- **Fee breakdown** — referral, fulfillment (FBA), variable closing, and other
  fees, with a total.
- **Net margin** — estimated net proceeds and margin after Amazon fees and
  product cost, plus a flag for listings below the channel's target margin.
- **Fee-aware floor** — extends the pricing module's price floor so a competitive
  push never drops a listing below the price needed to clear the target margin
  *after* fees.

A scheduled action (*Amazon: Sync Fees*, disabled by default) refreshes fee
estimates for active listings.
