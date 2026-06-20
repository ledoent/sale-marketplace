# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelWalmartSettlementGroup(models.Model):
    _name = "sale.channel.walmart.settlement.group"
    _description = "Sale Channel Walmart Settlement Group"
    _order = "settlement_date desc, id desc"
    _sql_constraints = [
        (
            "channel_settlement_uniq",
            "unique(sale_channel_id, walmart_settlement_id)",
            "A settlement is unique per channel.",
        ),
    ]

    sale_channel_id = fields.Many2one(
        "sale.channel", required=True, ondelete="cascade", index=True
    )
    walmart_settlement_id = fields.Char(required=True, index=True)
    settlement_date = fields.Datetime()
    original_total = fields.Float()
    currency_id = fields.Many2one("res.currency")
    account_move_id = fields.Many2one("account.move", string="Journal Entry")
    financial_event_ids = fields.One2many(
        "sale.channel.walmart.financial.event", "settlement_group_id"
    )
    reconciliation_ids = fields.One2many(
        "sale.channel.walmart.settlement.reconciliation", "settlement_group_id"
    )
