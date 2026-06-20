# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    sale_channel_type = fields.Selection(
        related="sale_channel_id.channel_type",
        string="Channel Type",
    )
    walmart_acknowledged = fields.Datetime(
        readonly=True,
        copy=False,
        help="When this order was acknowledged back to Walmart.",
    )
    walmart_cancelled = fields.Datetime(
        readonly=True,
        copy=False,
        help="When this order's cancellation was pushed to Walmart.",
    )
    walmart_collected_tax = fields.Float(
        readonly=True,
        copy=False,
        help="Sales tax Walmart collected and remits as a marketplace "
        "facilitator (informational; not an Odoo tax liability).",
    )

    def action_walmart_acknowledge(self):
        """Manually acknowledge the selected Walmart orders."""
        for order in self:
            channel = order.sale_channel_id
            if channel.channel_type == "walmart" and order.client_order_ref:
                channel._walmart_acknowledge_order(order.client_order_ref, order=order)
        return True

    def _action_cancel(self):
        # Cancellation actually happens here (action_cancel may first open the
        # cancel wizard), so this is the reliable hook to push to Walmart.
        res = super()._action_cancel()
        for order in self:
            order._walmart_enqueue_cancel()
        return res

    def _walmart_enqueue_cancel(self):
        self.ensure_one()
        channel = self.sale_channel_id
        if channel.channel_type != "walmart":
            return
        if not channel.walmart_auto_cancel or not self.client_order_ref:
            return
        if self.walmart_cancelled:
            return
        channel.with_delay(
            description=f"Cancel Walmart order {self.client_order_ref}"
        )._walmart_cancel_order(self.client_order_ref, order=self)

    def action_walmart_cancel(self):
        """Manually push a cancellation to Walmart for the selected orders."""
        for order in self:
            channel = order.sale_channel_id
            if channel.channel_type == "walmart" and order.client_order_ref:
                channel._walmart_cancel_order(order.client_order_ref, order=order)
        return True
