# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    walmart_tracking_pushed = fields.Datetime(readonly=True, copy=False)

    def _action_done(self):
        res = super()._action_done()
        for picking in self:
            picking._walmart_enqueue_ship_update()
        return res

    def _walmart_channel(self):
        self.ensure_one()
        channel = self.sale_id.sale_channel_id
        if channel and channel.channel_type == "walmart":
            return channel
        return self.env["sale.channel"]

    def _walmart_enqueue_ship_update(self):
        self.ensure_one()
        channel = self._walmart_channel()
        if not channel:
            return
        if self.picking_type_id.code != "outgoing":
            return
        if not self.carrier_tracking_ref or self.walmart_tracking_pushed:
            return
        channel.with_delay(
            description=f"Push Walmart shipment for {self.name}"
        )._walmart_confirm_shipment(self.sale_id.client_order_ref, self.id)

    def action_walmart_confirm_shipment(self):
        """Manual re-push of tracking to Walmart."""
        for picking in self:
            channel = picking._walmart_channel()
            if channel and picking.carrier_tracking_ref:
                channel._walmart_confirm_shipment(
                    picking.sale_id.client_order_ref, picking.id
                )
        return True
