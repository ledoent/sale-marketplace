# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models
from odoo.tools import float_compare


class SaleChannelProduct(models.Model):
    _inherit = "sale.channel.product"

    current_list_price = fields.Float(
        "Current Amazon Price",
        help="The price last pushed to / known on Amazon for this listing.",
    )
    buy_box_price = fields.Float(
        help="Latest competitive buy-box price seen for this ASIN."
    )
    buy_box_winner = fields.Boolean(
        "Wins Buy Box", help="Whether our offer currently wins the buy box."
    )
    price_history_ids = fields.One2many(
        "sale.channel.product.price.history",
        "sale_channel_product_id",
    )

    def _log_price_change(self, old_price, new_price, trigger, rule=False):
        """Record a price change in the audit trail (no-op if unchanged).

        Uses sudo so scheduled / queued price pushes can log regardless of the
        acting user's access to the history model.
        """
        self.ensure_one()
        history = self.env["sale.channel.product.price.history"]
        if float_compare(old_price, new_price, precision_digits=2) == 0:
            return history
        return history.sudo().create(
            {
                "sale_channel_product_id": self.id,
                "old_price": old_price,
                "new_price": new_price,
                "trigger": trigger,
                "rule": rule or False,
            }
        )
