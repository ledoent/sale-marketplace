# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelReturn(models.Model):
    _name = "sale.channel.return"
    _description = "Sale Channel Return"
    _order = "id desc"
    _sql_constraints = [
        (
            "channel_rma_uniq",
            "unique(sale_channel_id, rma_id)",
            "A return is unique per channel and RMA.",
        ),
    ]

    sale_channel_id = fields.Many2one(
        "sale.channel", required=True, ondelete="cascade", index=True
    )
    rma_id = fields.Char(required=True, index=True)
    amazon_order_id = fields.Char(index=True)
    order_id = fields.Many2one("sale.order")
    return_picking_id = fields.Many2one("stock.picking")
    credit_note_id = fields.Many2one("account.move")
    state = fields.Selection(
        [
            ("new", "New"),
            ("picking_created", "Restock Created"),
            ("credited", "Credited"),
            ("done", "Done"),
        ],
        default="new",
        required=True,
    )
    line_ids = fields.One2many("sale.channel.return.line", "return_id")


class SaleChannelReturnLine(models.Model):
    _name = "sale.channel.return.line"
    _description = "Sale Channel Return Line"

    return_id = fields.Many2one(
        "sale.channel.return", required=True, ondelete="cascade"
    )
    product_id = fields.Many2one("product.product")
    seller_sku = fields.Char()
    quantity = fields.Float(default=0.0)
    return_reason = fields.Char()
