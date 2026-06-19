# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    sale_channel_product_ids = fields.One2many(
        "sale.channel.product", "sale_channel_id", string="Channel Products"
    )
    sale_channel_product_count = fields.Integer(
        compute="_compute_sale_channel_product_count"
    )
    is_marketplace = fields.Boolean(
        compute="_compute_is_marketplace",
        help="Technical: the channel type is a marketplace "
        "(third-party platform such as Amazon or eBay).",
    )

    @api.model
    def _marketplace_channel_types(self):
        """Channel types that are marketplaces.

        Marketplace modules override this to register their own ``channel_type``
        (e.g. ``"amazon"``) so generic code can target marketplace channels.
        """
        return []

    @api.depends("channel_type")
    def _compute_is_marketplace(self):
        marketplace_types = self._marketplace_channel_types()
        for channel in self:
            channel.is_marketplace = channel.channel_type in marketplace_types

    @api.depends("sale_channel_product_ids")
    def _compute_sale_channel_product_count(self):
        data = self.env["sale.channel.product"]._read_group(
            [("sale_channel_id", "in", self.ids)],
            ["sale_channel_id"],
            ["__count"],
        )
        mapped = {channel.id: count for channel, count in data}
        for channel in self:
            channel.sale_channel_product_count = mapped.get(channel.id, 0)
