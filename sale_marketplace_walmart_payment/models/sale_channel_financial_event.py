# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelWalmartFinancialEvent(models.Model):
    _name = "sale.channel.walmart.financial.event"
    _description = "Sale Channel Walmart Financial Event"
    _order = "posted_date desc, id desc"

    settlement_group_id = fields.Many2one(
        "sale.channel.walmart.settlement.group",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sale_channel_id = fields.Many2one(
        related="settlement_group_id.sale_channel_id", store=True
    )
    event_type = fields.Selection(
        [
            ("sale", "Sale"),
            ("refund", "Refund"),
            ("commission", "Commission"),
            ("shipping", "Shipping"),
            ("tax", "Tax"),
            ("other", "Other"),
        ],
        required=True,
    )
    purchase_order_id = fields.Char(index=True)
    posted_date = fields.Datetime()
    amount = fields.Float(help="Signed amount as reported by Walmart.")
    description = fields.Char()
    currency_id = fields.Many2one("res.currency")
