This module pushes carrier tracking numbers back to Amazon when a delivery is
validated, via the SP-API `ConfirmShipment` endpoint.

When an outgoing picking linked to an Amazon `sale.channel` order is done and
carries a tracking reference, it enqueues a job that maps the Odoo carrier to
an Amazon carrier code and confirms the shipment (with order item ids fetched
from the order). A manual *Push Tracking to Amazon* button allows re-pushing.
