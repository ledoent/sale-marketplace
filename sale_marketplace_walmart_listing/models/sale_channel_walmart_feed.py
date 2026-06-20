# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannelWalmartFeed(models.Model):
    _name = "sale.channel.walmart.feed"
    _description = "Sale Channel Walmart Feed"
    _order = "submitted_date desc, id desc"

    sale_channel_id = fields.Many2one(
        "sale.channel", required=True, ondelete="cascade", index=True
    )
    feed_id = fields.Char(required=True, index=True)
    feed_type = fields.Char(default="item")
    state = fields.Selection(
        [
            ("submitted", "Submitted"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="submitted",
        required=True,
    )
    items_received = fields.Integer(readonly=True)
    items_succeeded = fields.Integer(readonly=True)
    items_failed = fields.Integer(readonly=True)
    error_message = fields.Text(readonly=True)
    submitted_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
