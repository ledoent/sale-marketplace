# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class SaleChannelImporter(models.TransientModel):
    _inherit = "sale.channel.importer"

    def _get_product(self, line_data, company):
        """Resolve Amazon line products through the channel SKU binding first.

        For an Amazon channel the line ``product_code`` is the seller SKU; map it
        via ``sale.channel.product`` (external_id) before falling back to the
        generic ``default_code`` lookup.
        """
        channel = self.payload_id.sale_channel_id
        if channel.channel_type == "amazon":
            binding = self.env["sale.channel.product"].search(
                [
                    ("sale_channel_id", "=", channel.id),
                    ("external_id", "=", line_data["product_code"]),
                ],
                limit=1,
            )
            if binding:
                return binding.product_id
        return super()._get_product(line_data, company)

    def _prepare_sale_vals(self, data):
        vals = super()._prepare_sale_vals(data)
        channel = self.payload_id.sale_channel_id
        if channel.channel_type == "amazon" and channel.warehouse_id:
            vals["warehouse_id"] = channel.warehouse_id.id
        return vals

    def _prepare_sale_line(self, line_data, sale_order):
        vals = super()._prepare_sale_line(line_data, sale_order)
        if self.payload_id.sale_channel_id.channel_type == "amazon":
            vals["amazon_order_item_id"] = line_data.get("amazon_order_item_id")
        return vals
