# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelSettlementGroup(models.Model):
    _name = "sale.channel.settlement.group"
    _description = "Sale Channel Settlement Group"
    _order = "fund_transfer_date desc, id desc"
    _sql_constraints = [
        (
            "channel_group_uniq",
            "unique(sale_channel_id, amazon_group_id)",
            "A settlement group is unique per channel.",
        ),
    ]

    sale_channel_id = fields.Many2one(
        "sale.channel", required=True, ondelete="cascade", index=True
    )
    amazon_group_id = fields.Char(required=True, index=True)
    processing_status = fields.Char()
    fund_transfer_date = fields.Datetime()
    original_total = fields.Float()
    currency_id = fields.Many2one("res.currency")
    account_move_id = fields.Many2one("account.move", string="Journal Entry")
    financial_event_ids = fields.One2many(
        "sale.channel.financial.event", "settlement_group_id"
    )
    reconciliation_ids = fields.One2many(
        "sale.channel.settlement.reconciliation", "settlement_group_id"
    )
