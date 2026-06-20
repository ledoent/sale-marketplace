# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelWalmartSettlementReconciliation(models.Model):
    _name = "sale.channel.walmart.settlement.reconciliation"
    _description = "Sale Channel Walmart Settlement Reconciliation"
    _order = "id desc"

    settlement_group_id = fields.Many2one(
        "sale.channel.walmart.settlement.group",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sale_channel_id = fields.Many2one(
        related="settlement_group_id.sale_channel_id", store=True
    )
    purchase_order_id = fields.Char(index=True)
    order_id = fields.Many2one("sale.order")
    invoice_id = fields.Many2one("account.move")
    settled_principal = fields.Float()
    invoiced_total = fields.Float()
    variance = fields.Float()
    state = fields.Selection(
        [
            ("matched", "Matched"),
            ("variance", "Variance"),
            ("no_invoice", "No Invoice"),
        ],
        required=True,
    )

    def action_open_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.invoice_id.id,
            "view_mode": "form",
        }
