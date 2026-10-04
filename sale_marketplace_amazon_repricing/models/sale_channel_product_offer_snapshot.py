# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelProductOfferSnapshot(models.Model):
    _name = "sale.channel.product.offer.snapshot"
    _description = "Sale Channel Product Offer Snapshot"
    _order = "date desc, id desc"

    sale_channel_product_id = fields.Many2one(
        "sale.channel.product",
        string="Channel Product",
        required=True,
        ondelete="cascade",
        index=True,
    )
    seller_id = fields.Char("Seller ID")
    is_own_offer = fields.Boolean()
    is_buy_box_winner = fields.Boolean()
    price = fields.Float()
    date = fields.Datetime(default=fields.Datetime.now, index=True)
