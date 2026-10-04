# Amazon connector

The Amazon addons extend OCA sale-channel for Odoo 18.0 and use `python-amazon-sp-api`.
They are Alpha modules. See each addon’s `readme/` fragments for configuration and the
[testing guide](amazon-testing.md) for test setup.

## What happens to an order

A disabled-by-default cron enqueues one polling job per active Amazon channel. Polling
uses `LastUpdatedAfter`, follows pagination, skips pending/cancelled/ unfulfillable
orders, and enqueues a job per order. The cursor is captured before polling so updates
during the poll remain eligible on the next run.

The order job fetches all item pages and the shipping address, maps them to a
`sale_import_base` payload, and lets that framework enqueue processing. Products resolve
through the channel's seller-SKU binding, then the generic product-code lookup. The
framework creates the partner binding and native sale order; its channel configuration
controls confirmation/invoicing. Existing sale orders with the same channel and Amazon
reference are skipped. Concurrent duplicate import and upstream order amendments still
need acceptance testing.

Each sale line retains `OrderItemId`. A completed outgoing picking sends its actual
moved quantity, converted to the product unit, against those item IDs. For an order of
three units delivered as one plus two, the first confirmation is one unit and the
backorder confirmation is two. The numeric picking ID is the stable package reference.
Missing mappings, fractional units, wrong-order and unfinished deliveries are rejected.
Retrying uses the same package reference.

Older imported orders have no retained item ID. Map their lines against the original
Amazon order before pushing tracking; do not guess from SKU where an order repeats a
SKU. A data migration cannot safely infer that relationship.

## Financial and external-write boundaries

The current order mapper uses item price divided by ordered quantity. It does **not**
fully map Amazon shipping charges, tax or promotional adjustments, or validate every
marketplace currency/pricelist combination. Do not enable automatic invoicing on the
assumption that the imported total matches Amazon.

Settlement polling revisits the preceding 179 days because the API filters by group
opening date, not closure date. This catches groups that close on a later poll. Older
groups require backfill. A processing failure propagates and prevents a successful-sync
timestamp; normal queue transaction rollback allows retry. Groups already linked to an
entry are not booked again.

Settlement entries remain **draft**. The parser covers selected shipment, refund,
service-fee and advertising event lists, not every Amazon financial event. Balancing a
journal entry does not prove it matches the disbursement. Review the event coverage and
account mapping, especially where sale invoices have already recognized revenue. Unknown
currencies and foreign-currency entries are rejected. The operation called
reconciliation compares principal to the first posted customer invoice's untaxed amount;
it does not reconcile receivable move lines.

Buy Shipping requires real package dimensions in centimeters and packed weight in
kilograms. The request includes order and item IDs; changing the package invalidates the
quote. Labels are base64 decoded, gzip decompressed and checked against the supplied
checksum. A recorded purchase prevents another purchase for the same delivery.
**Amazon's purchase cannot roll back with Odoo**: after a timeout or local save failure,
check Seller Central before retrying. Exactly-once purchase and automated
ambiguous-result recovery are not implemented.

## Security and operations

Client secrets and refresh tokens are restricted to Odoo system users. They are stored
as Odoo fields, not in a separate secret vault. Review administrator access, database
backups and logging accordingly. Company record rules cover channels, bindings and the
added persistent operational records; records on a shared company-less channel remain
shared.

Scheduled actions ship inactive. Configure one isolated seller/channel first. Keep
price/inventory writes, return automation, label buying and MCF submission disabled
until their acceptance cases pass. Queue jobs provide visibility and transaction
boundaries; an arbitrary external exception is not a promise of automatic retry. Inspect
failed jobs and the remote outcome before rerunning operations with external side
effects.
