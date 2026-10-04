This module buys Amazon merchant-fulfilled shipping labels through the
Merchant Fulfillment API. Enter the actual packed weight in kilograms and package
dimensions in centimeters, fetch rates, and select a service for the delivery.

Requests include the Amazon order ID and mapped order items. Changing package
details invalidates the selected quote. Label documents are decoded, decompressed,
and checksum-validated before they are attached with their correct file type.
The shipment record captures the tracking number, service, and cost.

A successfully recorded purchase blocks another purchase for that delivery.
Amazon's purchase is external to the Odoo transaction: a timeout or a failure
saving the response can leave a purchased label at Amazon without a local record.
Check Seller Central before retrying an ambiguous purchase. No automatic recovery
or exactly-once purchase guarantee is provided.

Purchased-label deliveries skip the separate tracking confirmation job.
