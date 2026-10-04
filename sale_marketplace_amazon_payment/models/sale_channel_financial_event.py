# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelFinancialEvent(models.Model):
    _name = "sale.channel.financial.event"
    _description = "Sale Channel Financial Event"
    _order = "posted_date desc, id desc"

    settlement_group_id = fields.Many2one(
        "sale.channel.settlement.group", required=True, ondelete="cascade", index=True
    )
    sale_channel_id = fields.Many2one(
        related="settlement_group_id.sale_channel_id", store=True
    )
    event_type = fields.Selection(
        [
            ("shipment", "Shipment"),
            ("refund", "Refund"),
            ("referral_fee", "Referral Fee"),
            ("fba_fee", "FBA Fee"),
            ("service_fee", "Service Fee"),
            ("advertising", "Advertising"),
            ("tax", "Tax"),
            ("shipping", "Shipping"),
            ("promotion", "Promotion"),
            ("other", "Other"),
        ],
        required=True,
    )
    amazon_order_id = fields.Char(index=True)
    posted_date = fields.Datetime()
    amount = fields.Float(help="Signed amount as reported by Amazon.")
    description = fields.Char()
    currency_id = fields.Many2one("res.currency")
