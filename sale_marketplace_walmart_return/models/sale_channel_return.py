# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelWalmartReturn(models.Model):
    _name = "sale.channel.walmart.return"
    _description = "Sale Channel Walmart Return"
    _order = "id desc"
    _sql_constraints = [
        (
            "channel_return_uniq",
            "unique(sale_channel_id, return_order_id)",
            "A return is unique per channel and return order.",
        ),
    ]

    sale_channel_id = fields.Many2one(
        "sale.channel", required=True, ondelete="cascade", index=True
    )
    return_order_id = fields.Char(required=True, index=True)
    purchase_order_id = fields.Char(index=True)
    order_id = fields.Many2one("sale.order")
    return_picking_id = fields.Many2one("stock.picking")
    credit_note_id = fields.Many2one("account.move")
    walmart_refund_id = fields.Char(readonly=True, copy=False)
    walmart_refund_issued = fields.Datetime(readonly=True, copy=False)
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
    line_ids = fields.One2many("sale.channel.walmart.return.line", "return_id")

    def action_walmart_issue_refund(self):
        """Manually push a Walmart refund for the selected returns."""
        for ret in self:
            ret.sale_channel_id._walmart_issue_refund(ret)
        return True


class SaleChannelWalmartReturnLine(models.Model):
    _name = "sale.channel.walmart.return.line"
    _description = "Sale Channel Walmart Return Line"

    return_id = fields.Many2one(
        "sale.channel.walmart.return", required=True, ondelete="cascade"
    )
    product_id = fields.Many2one("product.product")
    seller_sku = fields.Char("Seller SKU")
    quantity = fields.Float(default=0.0)
    return_reason = fields.Char()
