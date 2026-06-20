# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import datetime
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

_EPOCH = datetime.datetime(1970, 1, 1)

# Carrier name prefix -> Walmart carrier value (case-insensitive match).
# Unknown carriers are sent via the otherCarrier field.
_CARRIER_CODE_MAP = {
    "ups": "UPS",
    "usps": "USPS",
    "fedex": "FedEx",
    "dhl": "DHL",
    "ontrac": "OnTrac",
    "lasership": "LS",
}


def _walmart_carrier_name(carrier_name):
    """Build the Walmart ``carrierName`` node for a carrier display name."""
    name_lower = (carrier_name or "").lower()
    for prefix, code in _CARRIER_CODE_MAP.items():
        if name_lower.startswith(prefix):
            return {"carrier": code}
    return {"otherCarrier": carrier_name or "Other"}


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    def _walmart_confirm_shipment(self, purchase_order_id, picking_id):
        """Push a picking's carrier tracking number to the Walmart shipping API."""
        self.ensure_one()
        picking = self.env["stock.picking"].browse(picking_id)
        if not picking.exists():
            _logger.warning(
                "Picking %s no longer exists; skipping tracking push.", picking_id
            )
            return
        tracking_ref = picking.carrier_tracking_ref
        if not tracking_ref:
            _logger.warning("Picking %s has no tracking ref; skipping.", picking.name)
            return
        ship_date = picking.date_done or picking.scheduled_date
        if not ship_date:
            _logger.warning("Picking %s has no ship date; skipping.", picking.name)
            return
        # Walmart rejects a future ship date (can happen on the manual re-push
        # path when only scheduled_date is set).
        ship_date = min(ship_date, fields.Datetime.now())
        ship_ms = int((ship_date - _EPOCH).total_seconds() * 1000)

        carrier_name = picking.carrier_id.name if picking.carrier_id else ""
        token = self._walmart_get_token()
        order_data = self._walmart_fetch_order(purchase_order_id, token=token)

        tracking_info = {
            "shipDateTime": ship_ms,
            "carrierName": _walmart_carrier_name(carrier_name),
            "methodCode": "Standard",
            "trackingNumber": tracking_ref,
        }
        ship_lines = [
            self._walmart_line_status(line, "Shipped", {"trackingInfo": tracking_info})
            for line in self._walmart_order_lines(order_data)
        ]
        if not ship_lines:
            _logger.warning(
                "Walmart order %s has no lines to ship; skipping.", purchase_order_id
            )
            return

        payload = {"orderShipment": {"orderLines": {"orderLine": ship_lines}}}
        self._walmart_request(
            "POST",
            f"/v3/orders/{purchase_order_id}/shipping",
            payload=payload,
            token=token,
        )
        _logger.info(
            "Pushed tracking %s for Walmart order %s.", tracking_ref, purchase_order_id
        )
        picking.walmart_tracking_pushed = fields.Datetime.now()
