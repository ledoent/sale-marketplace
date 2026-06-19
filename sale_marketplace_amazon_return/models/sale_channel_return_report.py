# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelReturnReport(models.Model):
    _name = "sale.channel.return.report"
    _description = "Sale Channel Return Report"
    _order = "id desc"

    sale_channel_id = fields.Many2one(
        "sale.channel", required=True, ondelete="cascade", index=True
    )
    amazon_report_id = fields.Char(index=True)
    document_id = fields.Char()
    state = fields.Selection(
        [
            ("requested", "Requested"),
            ("done", "Done"),
            ("parsed", "Parsed"),
            ("error", "Error"),
        ],
        default="requested",
        required=True,
    )
    error_message = fields.Char()
