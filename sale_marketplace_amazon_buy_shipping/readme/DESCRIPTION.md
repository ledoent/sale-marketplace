This module buys Amazon merchant-fulfilled (MFN) shipping labels through the
Merchant Fulfillment API:

- From an outgoing delivery of an Amazon order, fetch eligible shipping services
  and rates, choose one, and purchase the label.
- The purchased label is stored as an attachment, the tracking number is written
  back to the delivery, and a shipment record captures carrier, service and cost.
- Buying a label already notifies Amazon of the shipment, so the separate
  ConfirmShipment tracking push is skipped for purchased-label deliveries.

The shipment record and the tracking write happen in a single transaction, so a
failure never leaves an orphaned shipment.
