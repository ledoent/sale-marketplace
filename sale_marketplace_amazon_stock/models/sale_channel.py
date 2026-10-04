# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)

# Carrier name prefix -> SP-API carrier code (case-insensitive match)
_CARRIER_CODE_MAP = {
    "ups": "UPS",
    "usps": "USPS",
    "fedex": "FedEx",
    "dhl": "DHL",
    "amazon": "Amazon",
    "ontrac": "OnTrac",
    "lasership": "LaserShip",
    "uds": "UDS",
}


def _map_carrier_code(carrier_name):
    name_lower = (carrier_name or "").lower()
    for prefix, code in _CARRIER_CODE_MAP.items():
        if name_lower.startswith(prefix):
            return code
    return "Other"


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    def _amazon_picking_items(self, picking, done_only=True):
        """Map a picking's quantities to whole Amazon order-item quantities."""
        self.ensure_one()
        quantities = {}
        for move in picking.move_ids.filtered(
            lambda m: m.state == "done" if done_only else m.state != "cancel"
        ):
            quantity = move.product_uom._compute_quantity(
                move.quantity, move.product_id.uom_id, round=False
            )
            if quantity <= 0:
                continue
            item_id = move.sale_line_id.amazon_order_item_id
            if not item_id:
                raise UserError(
                    _("Missing Amazon order item on delivery line %s.") % move.name
                )
            quantities[item_id] = quantities.get(item_id, 0.0) + quantity
        items = []
        for item_id, quantity in quantities.items():
            if float_compare(quantity, round(quantity), precision_digits=6):
                raise UserError(_("Amazon shipment quantities must be whole units."))
            items.append({"orderItemId": item_id, "quantity": int(round(quantity))})
        if not items:
            raise UserError(_("There are no completed Amazon items to confirm."))
        return items

    def _amazon_confirm_shipment(self, amazon_order_id, picking_id):
        """Push a picking's carrier tracking number to Amazon ConfirmShipment."""
        self.ensure_one()
        from sp_api.api import Orders
        from sp_api.base import SellingApiException

        picking = self.env["stock.picking"].browse(picking_id)
        if not picking.exists():
            _logger.warning(
                "Picking %s no longer exists; skipping tracking push.", picking_id
            )
            return
        if (
            picking.state != "done"
            or picking.picking_type_id.code != "outgoing"
            or picking.sale_id.sale_channel_id != self
            or picking.sale_id.client_order_ref != amazon_order_id
        ):
            raise UserError(
                _("Only a completed delivery for this Amazon order can be confirmed.")
            )
        order_items = self._amazon_picking_items(picking)
        tracking_ref = picking.carrier_tracking_ref
        if not tracking_ref:
            _logger.warning("Picking %s has no tracking ref; skipping.", picking.name)
            return
        ship_date = picking.date_done or picking.scheduled_date
        if not ship_date:
            _logger.warning("Picking %s has no ship date; skipping.", picking.name)
            return
        # Amazon rejects a future ship date (can happen on the manual re-push
        # path when only scheduled_date is set).
        ship_date = min(ship_date, fields.Datetime.now())

        carrier_name = picking.carrier_id.name if picking.carrier_id else ""
        api = self._amazon_get_api(Orders)
        try:
            # sp_api confirm_shipment sends its **kwargs as the POST body;
            # the request fields must be passed directly, not wrapped in payload=.
            api.confirm_shipment(
                amazon_order_id,
                marketplaceId=self.amazon_marketplace_id,
                packageDetail={
                    "packageReferenceId": str(picking.id),
                    "carrierCode": _map_carrier_code(carrier_name),
                    "carrierName": carrier_name,
                    "trackingNumber": tracking_ref,
                    "shipDate": ship_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "orderItems": order_items,
                },
            )
            _logger.info(
                "Pushed tracking %s for Amazon order %s.", tracking_ref, amazon_order_id
            )
        except SellingApiException as exc:
            _logger.error(
                "ConfirmShipment failed for Amazon order %s: %s", amazon_order_id, exc
            )
            raise
        picking.amazon_tracking_pushed = fields.Datetime.now()
