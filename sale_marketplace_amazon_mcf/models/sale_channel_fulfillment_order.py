# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "RECEIVED": "processing",
    "PLANNING": "processing",
    "PROCESSING": "processing",
    "COMPLETE": "complete",
    "COMPLETE_PARTIALLED": "complete",
    "CANCELLED": "cancelled",
    "INVALID": "invalid",
}


class SaleChannelFulfillmentOrder(models.Model):
    _name = "sale.channel.fulfillment.order"
    _description = "Sale Channel MCF Fulfillment Order"
    _order = "id desc"

    name = fields.Char(required=True, help="Seller fulfillment order id.")
    sale_channel_id = fields.Many2one("sale.channel", required=True, ondelete="cascade")
    picking_id = fields.Many2one("stock.picking", ondelete="cascade")
    partner_id = fields.Many2one("res.partner")
    shipping_speed = fields.Selection(
        [
            ("Standard", "Standard"),
            ("Expedited", "Expedited"),
            ("Priority", "Priority"),
        ],
        default="Standard",
    )
    displayable_order_id = fields.Char()
    amazon_status = fields.Char(readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("processing", "Processing"),
            ("complete", "Complete"),
            ("cancelled", "Cancelled"),
            ("invalid", "Invalid"),
        ],
        default="draft",
        required=True,
    )
    line_ids = fields.One2many(
        "sale.channel.fulfillment.order.line", "fulfillment_order_id"
    )
    tracking_numbers = fields.Char(readonly=True)
    carrier = fields.Char(readonly=True)

    def action_submit(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Only draft fulfillment orders can be submitted."))
        if not self.line_ids:
            raise UserError(_("Add at least one line before submitting."))
        self.sale_channel_id._amz_create_fulfillment_order(self)
        self.state = "submitted"
        return True

    def action_check_status(self):
        self.ensure_one()
        payload = self.sale_channel_id._amz_get_fulfillment_order(self)
        self._sync_status(payload)
        return True

    def action_cancel(self):
        self.ensure_one()
        if self.state in ("complete", "cancelled"):
            raise UserError(_("This fulfillment order cannot be cancelled."))
        if self.state == "submitted":
            self.sale_channel_id._amz_cancel_fulfillment_order(self)
        self.state = "cancelled"
        return True

    def _sync_status(self, payload):
        self.ensure_one()
        payload = payload or {}
        status = payload.get("fulfillmentOrder", {}).get("fulfillmentOrderStatus")
        if status:
            self.amazon_status = status
            self.state = _STATUS_MAP.get(status, self.state)
        tracking = []
        carrier = False
        # an MCF order can split across multiple shipments, each with multiple
        # packages -- collect tracking from all of them, not just the first.
        for shipment in payload.get("fulfillmentShipments", []):
            for package in shipment.get("fulfillmentShipmentPackage", []):
                number = package.get("trackingNumber")
                if number:
                    tracking.append(number)
                carrier = carrier or package.get("carrierCode")
        if tracking:
            self.tracking_numbers = ", ".join(tracking)
            self.carrier = carrier
            if self.picking_id and not self.picking_id.carrier_tracking_ref:
                self.picking_id.carrier_tracking_ref = tracking[0]

    @api.model
    def _cron_amazon_sync_mcf_status(self):
        orders = self.search([("state", "in", ("submitted", "processing"))])
        for order in orders:
            try:
                order.action_check_status()
            except Exception as exc:  # pragma: no cover - isolate per order
                _logger.warning("MCF status sync failed for %s: %s", order.name, exc)


class SaleChannelFulfillmentOrderLine(models.Model):
    _name = "sale.channel.fulfillment.order.line"
    _description = "Sale Channel MCF Fulfillment Order Line"

    fulfillment_order_id = fields.Many2one(
        "sale.channel.fulfillment.order", required=True, ondelete="cascade"
    )
    product_id = fields.Many2one("product.product", required=True)
    seller_sku = fields.Char(required=True)
    item_id = fields.Char(help="Seller fulfillment order item id.")
    quantity = fields.Float(default=1.0)
