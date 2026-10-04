# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    amazon_label_purchased = fields.Boolean(readonly=True, copy=False)
    is_amazon_order = fields.Boolean(compute="_compute_is_amazon_order")

    @api.depends("sale_id.sale_channel_id")
    def _compute_is_amazon_order(self):
        for picking in self:
            picking.is_amazon_order = bool(picking._amazon_channel())

    def _amazon_enqueue_confirm_shipment(self):
        # Buying a Merchant Fulfillment label already notifies Amazon of the
        # shipment, so skip the separate ConfirmShipment push for those pickings.
        self.ensure_one()
        if self.amazon_label_purchased:
            return
        return super()._amazon_enqueue_confirm_shipment()

    def action_amazon_buy_shipping(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Buy Amazon Shipping",
            "res_model": "sale.channel.buy.shipping.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_picking_id": self.id},
        }
