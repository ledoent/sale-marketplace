# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelWalmartLog(models.Model):
    _name = "sale.channel.walmart.log"
    _description = "Sale Channel Walmart Log"
    _order = "date desc, id desc"

    sale_channel_id = fields.Many2one(
        "sale.channel", required=True, ondelete="cascade", index=True
    )
    operation = fields.Char(index=True, help="The sync operation that logged this.")
    level = fields.Selection(
        [("info", "Info"), ("warning", "Warning"), ("error", "Error")],
        default="info",
        required=True,
        index=True,
    )
    message = fields.Text()
    reference = fields.Char(
        index=True, help="Related external id (SKU, purchase order, feed id…)."
    )
    date = fields.Datetime(default=fields.Datetime.now, index=True)
