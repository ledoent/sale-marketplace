# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models
from odoo.tools import float_compare


class SaleChannelProduct(models.Model):
    _inherit = "sale.channel.product"

    walmart_list_price = fields.Float(
        "Current Walmart Price",
        help="The price last pushed to / known on Walmart for this listing.",
    )
    walmart_price_history_ids = fields.One2many(
        "sale.channel.product.walmart.price.history",
        "sale_channel_product_id",
    )

    def _walmart_log_price_change(self, old_price, new_price, trigger):
        """Record a price change in the audit trail (no-op if unchanged).

        Uses sudo so scheduled / queued price pushes can log regardless of the
        acting user's access to the history model.
        """
        self.ensure_one()
        history = self.env["sale.channel.product.walmart.price.history"]
        if float_compare(old_price, new_price, precision_digits=2) == 0:
            return history
        return history.sudo().create(
            {
                "sale_channel_product_id": self.id,
                "old_price": old_price,
                "new_price": new_price,
                "trigger": trigger,
            }
        )
