Import Walmart Marketplace settlements into Odoo as balanced journal entries and
reconcile settled revenue to customer invoices.

Settlement transactions are pulled per channel, grouped by settlement, and
classified into financial events (sale, refund, commission, shipping, tax). Each
settlement produces one balanced journal entry: revenue-side amounts post to the
income account, fees to the fee account (a fee is never routed to income), with a
bank/clearing line offsetting the disbursement. Settled principal per order is
then reconciled against its posted customer invoice, flagging matched / variance
/ no-invoice. A bad settlement in a batch is isolated and logged. Cron + manual
**Sync Settlements** action, both via queue jobs.
