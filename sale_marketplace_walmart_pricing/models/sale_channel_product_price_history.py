# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelProductWalmartPriceHistory(models.Model):
    _name = "sale.channel.product.walmart.price.history"
    _description = "Sale Channel Product Walmart Price History"
    _order = "date desc, id desc"

    sale_channel_product_id = fields.Many2one(
        "sale.channel.product",
        string="Channel Product",
        required=True,
        ondelete="cascade",
        index=True,
    )
    old_price = fields.Float()
    new_price = fields.Float()
    trigger = fields.Selection(
        [
            ("manual", "Manual"),
            ("cron", "Scheduled"),
        ],
        default="manual",
        required=True,
    )
    date = fields.Datetime(default=fields.Datetime.now, index=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user)
