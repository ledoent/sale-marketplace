This module pushes carrier tracking numbers back to Amazon for completed
outgoing deliveries via the SP-API ConfirmShipment endpoint.

It sends only the quantities actually completed on that delivery, using the
Amazon order-item IDs retained on the imported sale lines. Partial deliveries
and backorders therefore have separate package references and quantities.
Missing item mappings and unfinished deliveries are rejected before an API call.

Older imported orders without item IDs need their sale lines mapped against the
original Amazon order before tracking can be pushed. Never infer an item ID from
SKU alone where an order contains repeated SKUs. A manual Push Tracking to Amazon
button permits resending the same delivery/package reference.
